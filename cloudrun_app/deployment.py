"""Fail early on unsafe production topology; values attest real platform settings."""
import os


def deployment_errors(env=None):
    env = os.environ if env is None else env
    errors = []
    if not env.get('ALLOWED_APPIDS', '').strip():
        errors.append('必须配置 ALLOWED_APPIDS 白名单')
    if env.get('JOB_QUEUE_BACKEND') != 'mysql':
        errors.append('正式部署须使用外部 MySQL 任务队列，SQLite 仅供本地/单容器测试')
    for key in ('JOB_DB_HOST', 'JOB_DB_NAME', 'JOB_DB_USER', 'JOB_DB_PASSWORD',
                'COS_REGION', 'COS_BUCKET', 'TENCENTCLOUD_SECRETID', 'TENCENTCLOUD_SECRETKEY'):
        if not env.get(key):
            errors.append('缺少 ' + key)
    if env.get('CLOUDRUN_ACCESS_MODE') != 'miniapp-only':
        errors.append('须在平台关闭 PUBLIC/OA 公网访问，再设置 CLOUDRUN_ACCESS_MODE=miniapp-only')
    if env.get('WORKER_EXECUTION_MODE') != 'continuous':
        errors.append('须确认持续 CPU 的运行模式，再设置 WORKER_EXECUTION_MODE=continuous；请求结束即停 CPU 的模式不可用')
    try:
        if int(env.get('MAX_INFLIGHT', '1')) < 1 or int(env.get('MAX_ASYNC_PENDING', '8')) < 1:
            errors.append('并发数和排队上限必须为正整数')
        if not 1 <= float(env.get('COMPUTE_TIMEOUT_SECONDS', '300')) <= 600:
            errors.append('COMPUTE_TIMEOUT_SECONDS 必须在 1 到 600 秒之间')
    except ValueError:
        errors.append('并发数/计算超时配置必须为有效数字')
    return errors


def validate_production():
    if os.environ.get('APP_ENV') == 'production':
        errors = deployment_errors()
        if errors:
            raise RuntimeError('生产部署检查未通过: ' + '; '.join(errors))


if __name__ == '__main__':
    errors = deployment_errors()
    print('\n'.join(errors) if errors else '生产部署配置检查通过；仍须核对平台实际网络与 CPU 运行模式')
    raise SystemExit(1 if errors else 0)
