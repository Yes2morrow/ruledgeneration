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
from pathlib import Path
from typing import Optional
from urllib.parse import quote


class StorageBackend:
    """存储后端接口。put_* 返回 {"url": ..., "fileId": ..., "key": ...}"""

    name = "base"

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
        return f"{self.base_url}/api/runs/files/{quote(key)}"

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
        p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


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
        except Exception:  # noqa: BLE001  COS 对象不存在会抛异常, 按 miss 处理
            return None

    def put_json(self, key: str, payload: dict) -> None:
        self.put_bytes(
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            key,
            "application/json",
        )


_COS_REQUIRED = ("COS_REGION", "COS_BUCKET", "TENCENTCLOUD_SECRETID", "TENCENTCLOUD_SECRETKEY")


def build_storage(local_root: Path, base_url: str = "") -> StorageBackend:
    """优先云存储; 环境变量不全时自动回落到本地盘(单实例模式)。"""
    missing = [k for k in _COS_REQUIRED if not os.environ.get(k)]
    if not missing:
        return CosStorage()
    return LocalStorage(local_root, base_url)
