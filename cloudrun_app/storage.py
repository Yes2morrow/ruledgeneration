"""产物存储抽象。

云托管必须保持无状态: 多实例时 A 实例生成的图片, B 实例下载不到, 且实例缩容/重启后
本地文件全部丢失。因此产物与任务状态都要外置。

  - LocalStorage: 本地/单实例模式, 文件留在本地盘, url 走本服务的 /api/runs/files 路由。
  - CosStorage:   CloudBase 云存储(底层是 COS 桶), 返回预签名 URL。

两者对上层接口一致, 便于本地调试与灰度切换。
"""
from __future__ import annotations

import io
import json
import os
import hmac
import hashlib
import secrets
import tempfile
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urlsplit, unquote


class StorageBackend:
    """存储后端接口。put_* 返回 {"url": ..., "fileId": ..., "key": ...}"""

    name = "base"

    def refresh_url(self, url: str) -> str:
        return url

    def put_file(self, local_path: Path, key: str, content_type: str = "application/octet-stream") -> dict:
        raise NotImplementedError

    def put_bytes(self, data: bytes, key: str, content_type: str = "application/octet-stream") -> dict:
        raise NotImplementedError

    def get_json(self, key: str) -> Optional[dict]:
        raise NotImplementedError

    def put_json(self, key: str, payload: dict) -> None:
        raise NotImplementedError


class LocalStorage(StorageBackend):
    """本地盘模式。仅适用于 MinNum=MaxNum=1 的单实例部署, 或本地调试。"""

    name = "local"

    def __init__(self, root: Path, base_url: str = ""):
        self.root = root
        self.base_url = base_url.rstrip("/")
        self.root.mkdir(parents=True, exist_ok=True)
        key_path = self.root / '.file-signing-key'
        if not key_path.exists():
            fd, temp = tempfile.mkstemp(dir=self.root)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(secrets.token_bytes(32))
                try:
                    os.link(temp, key_path)
                except FileExistsError:
                    pass
            finally:
                os.unlink(temp)
        self.signing_key = key_path.read_bytes()

    def put_file(self, local_path: Path, key: str, content_type: str = "application/octet-stream") -> dict:
        import shutil

        dest = self.root / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        src = Path(local_path).resolve()
        if src != dest.resolve():
            shutil.copyfile(src, dest)
        return {"url": self._url(key), "fileId": "", "key": key}

    def put_bytes(self, data: bytes, key: str, content_type: str = "application/octet-stream") -> dict:
        dest = self.root / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return {"url": self._url(key), "fileId": "", "key": key}

    def _url(self, key: str) -> str:
        if not self.base_url:
            return ""
        expires = int(time.time()) + 7200
        signature = self._signature(key, expires)
        return f"{self.base_url}/api/runs/files/{quote(key)}?expires={expires}&signature={signature}"

    def _signature(self, key, expires):
        return hmac.new(self.signing_key, f'{key}:{expires}'.encode(), hashlib.sha256).hexdigest()

    def verify_url(self, key, expires, signature):
        return (key.startswith('plans/') and expires >= time.time()
                and len(signature) == 64 and all(c in '0123456789abcdef' for c in signature)
                and hmac.compare_digest(self._signature(key, expires), signature))

    def refresh_url(self, url):
        prefix = f'{self.base_url}/api/runs/files/'
        if url.startswith(prefix):
            key = unquote(urlsplit(url).path.split('/api/runs/files/', 1)[1])
            return self._url(key)
        return url

    def get_json(self, key: str) -> Optional[dict]:
        p = self.root / key
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return None

    def put_json(self, key: str, payload: dict) -> None:
        p = self.root / key
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=p.parent, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(payload, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, p)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)


class CosStorage(StorageBackend):
    """CloudBase 云存储。

    环境变量:
      COS_REGION / COS_BUCKET
      TENCENTCLOUD_SECRETID / TENCENTCLOUD_SECRETKEY
      TENCENTCLOUD_SESSIONTOKEN  使用临时密钥时必填
      TCB_ENV                    用于拼 cloud:// fileID
      COS_URL_TTL_SECONDS        预签名 URL 有效期, 默认 7200
    """

    name = "cos"

    def __init__(self):
        from qcloud_cos import CosConfig, CosS3Client  # noqa: PLC0415

        self.region = os.environ["COS_REGION"]
        self.bucket = os.environ["COS_BUCKET"]
        self.env_id = os.environ.get("TCB_ENV", "")
        self.ttl = int(os.environ.get("COS_URL_TTL_SECONDS", "7200"))

        config = CosConfig(
            Region=self.region,
            SecretId=os.environ["TENCENTCLOUD_SECRETID"],
            SecretKey=os.environ["TENCENTCLOUD_SECRETKEY"],
            Token=os.environ.get("TENCENTCLOUD_SESSIONTOKEN") or None,
            Scheme="https",
        )
        self.client = CosS3Client(config)

    def _file_id(self, key: str) -> str:
        if not self.env_id:
            return ""
        return f"cloud://{self.env_id}.{self.bucket}/{quote(key)}"

    def _sign(self, key: str) -> str:
        return self.client.get_presigned_download_url(
            Bucket=self.bucket, Key=key, Expired=self.ttl
        )

    def refresh_url(self, url):
        parsed = urlsplit(url)
        if parsed.hostname == f'{self.bucket}.cos.{self.region}.myqcloud.com':
            return self._sign(unquote(parsed.path.lstrip('/')))
        return url

    def put_file(self, local_path: Path, key: str, content_type: str = "application/octet-stream") -> dict:
        self.client.put_object_from_local_file(
            Bucket=self.bucket,
            LocalFilePath=str(local_path),
            Key=key,
            ContentType=content_type,
        )
        return {"url": self._sign(key), "fileId": self._file_id(key), "key": key}

    def put_bytes(self, data: bytes, key: str, content_type: str = "application/octet-stream") -> dict:
        self.client.put_object(
            Bucket=self.bucket, Body=io.BytesIO(data), Key=key, ContentType=content_type
        )
        return {"url": self._sign(key), "fileId": self._file_id(key), "key": key}

    def get_json(self, key: str) -> Optional[dict]:
        try:
            resp = self.client.get_object(Bucket=self.bucket, Key=key)
            return json.loads(resp["Body"].get_raw_stream().read().decode("utf-8"))
        except Exception as exc:
            if callable(getattr(exc, 'get_status_code', None)) and exc.get_status_code() == 404:
                return None
            raise  # Credential/network failures must not masquerade as missing jobs.

    def put_json(self, key: str, payload: dict) -> None:
        self.put_bytes(
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            key,
            "application/json",
        )


_COS_REQUIRED = ("COS_REGION", "COS_BUCKET", "TENCENTCLOUD_SECRETID", "TENCENTCLOUD_SECRETKEY")


def build_storage(local_root: Path, base_url: str = "") -> StorageBackend:
    """未启用 COS 时使用本地盘；部分 COS 配置必须报错，不能静默降级。"""
    missing = [k for k in _COS_REQUIRED if not os.environ.get(k)]
    if not missing:
        return CosStorage()
    if os.environ.get('COS_BUCKET') or os.environ.get('COS_REGION'):
        raise RuntimeError('COS 配置不完整，缺少: ' + ', '.join(missing))
    return LocalStorage(local_root, base_url)
