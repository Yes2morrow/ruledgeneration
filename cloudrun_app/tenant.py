"""多小程序租户识别。

云托管在小程序 wx.cloud.callContainer 链路中会注入 X-WX-* 系列请求头,
服务端据此区分是哪个小程序(appid)、哪个用户(openid / unionid)。

安全约束:
  这些头属于网关注入的敏感运行时数据, 只能在服务端读取。
  禁止把 header 内容回显到响应体, 禁止把完整 header 打进日志。
"""
from __future__ import annotations

import os
import hashlib
from typing import Iterable

# 允许接入的小程序 appid 白名单(逗号分隔)。为空表示不限制, 仅建议开发期使用。
_ALLOWED_APPIDS = frozenset(
    a.strip() for a in os.environ.get("ALLOWED_APPIDS", "").split(",") if a.strip()
)

# 注入头名称在不同平台版本可能有大小写差异, 统一取小写后匹配
_APPID_KEYS = ("x-wx-appid",)
_OPENID_KEYS = ("x-wx-openid",)
_UNIONID_KEYS = ("x-wx-unionid",)


def _pick(headers, keys: Iterable[str]) -> str:
    for k in keys:
        v = headers.get(k)
        if v:
            return v
    return ""


def read_tenant(request) -> dict:
    """解析租户身份。request 为 Starlette Request。"""
    headers = request.headers
    appid = _pick(headers, _APPID_KEYS)
    openid = _pick(headers, _OPENID_KEYS)
    unionid = _pick(headers, _UNIONID_KEYS)

    # 同一微信开放平台账号下的多个小程序, unionid 可打通用户身份;
    # 不同主体则拿不到 unionid, 退化为 appid + openid 作为用户键。
    if unionid:
        user_key = unionid
    elif appid and openid:
        user_key = f"{appid}:{openid}"
    else:
        user_key = ""

    return {
        "appid": appid or "unknown",
        "openid": openid,
        "unionid": unionid,
        "userKey": user_key,
        "authenticated": bool(openid or unionid),
    }


def assert_allowed(tenant: dict) -> None:
    """appid 白名单校验。未通过时抛 PermissionError。"""
    if _ALLOWED_APPIDS and tenant.get("appid") not in _ALLOWED_APPIDS:
        raise PermissionError("小程序未授权")
    if not tenant.get('authenticated') or tenant.get('appid') == 'unknown':
        raise PermissionError('缺少微信用户身份，请通过小程序访问')


def owner_key(tenant: dict) -> str:
    if tenant.get('owner'):
        return tenant['owner']
    # AppID remains part of the authorization boundary, including UnionID users.
    raw = f"{tenant['appid']}:{tenant.get('userKey', '')}"
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def header_names(request) -> list:
    """返回请求头的**名称列表**(不含值)。

    仅供上线前核对网关注入了哪些头, 排查用。切勿打印 header 的值。
    """
    return sorted(request.headers.keys())
