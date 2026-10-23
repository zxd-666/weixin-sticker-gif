"""Non-generative discovery, model contracts, secure credential access and consent."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from config_contract import ContractError, object_sha256, read_json_object

MODELS = {
    'grok': dict(provider_id='grok-build-local', platform='grok', model='image_to_video',
                 regions=['global'], resolutions=['480p', '720p'], duration=[6, 6],
                 default_resolution='720p', key_env=None, billing='subscription-or-unknown'),
    'minimax-h3': dict(provider_id='minimax-h3', platform='minimax', model='MiniMax-H3',
                       regions=['international', 'china'], resolutions=['768p', '2k'], duration=[4, 15],
                       default_resolution='768p', key_env='MINIMAX_API_KEY', billing='pay-as-you-go'),
    'wan3': dict(provider_id='wan3', platform='alibaba', model='wan3.0-video',
                regions=['international', 'china'], resolutions=['480p', '720p', '1080p'], duration=[2, 30],
                default_resolution='720p', key_env='DASHSCOPE_API_KEY', billing='pay-as-you-go'),
    'seedance-2-0': dict(provider_id='seedance-2-0', platform='bytedance', model='doubao-seedance-2-0-260128',
                         regions=['china'], resolutions=['720p'], duration=[4, 15],
                         default_resolution='720p', key_env='ARK_API_KEY', billing='pay-as-you-go'),
    'seedance-2-5': dict(provider_id='seedance-2-5', platform='bytedance', model='doubao-seedance-2-5-260628',
                         regions=['china'], resolutions=['720p'], duration=[4, 30],
                         default_resolution='720p', key_env='ARK_API_KEY', billing='pay-as-you-go'),
}
# Preserve the existing credential namespace across the project rename.
KEYCHAIN_SERVICE = 'motion-sticker-pack.video'


def now() -> datetime:
    return datetime.now(timezone.utc)


def stamp() -> str:
    return now().isoformat()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def model_spec(name: str, region: str) -> dict:
    if name not in MODELS or region not in MODELS[name]['regions']:
        raise ContractError('请选择支持的模型和地域；运行 configure_video.py models 查看')
    return {**MODELS[name], 'catalog_id': name, 'region': region}


def recent(value: str, *, seconds: int = 3600) -> bool:
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        age = (now() - dt).total_seconds()
        return 0 <= age <= seconds
    except (TypeError, ValueError):
        return False


def secure_keyring():
    try:
        import keyring
        backend = keyring.get_keyring()
        # Reject null/plaintext/third-party fallback backends, including Chainer.
        module = type(backend).__module__
        if module not in {'keyring.backends.macOS', 'keyring.backends.Windows',
                          'keyring.backends.SecretService', 'keyring.backends.libsecret'}:
            raise ContractError('没有受支持的系统凭据库；请使用对应环境变量')
        return keyring
    except ImportError as exc:
        raise ContractError('未安装 keyring；可使用环境变量或安装项目 requirements.txt') from exc


def credential(name: str, region: str) -> str | None:
    spec = model_spec(name, region)
    env = spec['key_env']
    if not env:
        return None
    value = os.environ.get(env)
    if value:
        return value
    try:
        return secure_keyring().get_password(KEYCHAIN_SERVICE, f"{spec['platform']}:{region}")
    except ContractError:
        raise
    except Exception as exc:
        raise ContractError('系统凭据库当前不可读取；无法判断 Key 是否已配置，请检查钥匙串访问权限') from exc


def save_credential(name: str, region: str, value: str) -> None:
    spec = model_spec(name, region)
    if not spec['key_env'] or not value or any(ch in value for ch in '\r\n\0'):
        raise ContractError('Key 格式无效或该入口不需要 Key')
    secure_keyring().set_password(KEYCHAIN_SERVICE, f"{spec['platform']}:{region}", value)


def credential_fingerprint(selection: dict) -> str:
    if not model_spec(selection['catalog_id'], selection['region'])['key_env']:
        auth = Path(os.environ.get('GROK_HOME', str(Path.home() / '.grok'))) / 'auth.json'
        if not auth.is_file():
            raise ContractError('未找到 Grok 登录缓存，请先登录并检查 /usage')
        return file_hash(auth)
    key = credential(selection['catalog_id'], selection['region'])
    if not key:
        raise ContractError('费用确认前请先配置所选地域的 Key')
    return hashlib.sha256(key.encode()).hexdigest()


def discover(runtime_tools: dict | None = None) -> dict:
    """Passive checks only: no inference, quota guesses, cookie export or login."""
    tools = []
    for name in ['grok', 'minimax', 'qwen', 'claude', 'codex']:
        binary = shutil.which(name)
        tools.append({'name': name, 'installed': bool(binary), 'executable': binary,
                      'video_capability': 'unknown', 'account_status': 'unknown'})
    grok = tools[0]
    home = Path(os.environ.get('GROK_HOME', str(Path.home() / '.grok')))
    auth = home / 'auth.json'
    if grok['installed'] and auth.is_file():
        try:
            values = json.loads(auth.read_text())
            for entry in values.values():
                if not isinstance(entry, dict):
                    continue
                expires = datetime.fromisoformat(entry['expires_at'].replace('Z', '+00:00'))
                if expires > now():
                    grok.update(account_status='cached-login', auth_mode=entry.get('auth_mode'),
                                video_capability='requires-live-confirmation',
                                retention_opt_out=bool(entry.get('coding_data_retention_opt_out')))
                    break
        except (OSError, ValueError, KeyError, TypeError):
            grok['account_status'] = 'unverified-cache'
    runtime = []
    for tool in (runtime_tools or {}).get('tools', []):
        if isinstance(tool, dict) and tool.get('available') and 'image-to-video' in tool.get('capabilities', []):
            runtime.append({'id': tool.get('id'), 'source': 'runtime-manifest',
                            'video_capability': 'declared-image-to-video',
                            'account_status': 'requires-live-confirmation'})
    keys = [{'model': key, 'environment': spec['key_env'],
             'environment_present': bool(os.environ.get(spec['key_env'], ''))}
            for key, spec in MODELS.items() if spec['key_env']]
    return {'version': 1, 'checked_at': stamp(), 'generation_performed': False,
            'tools': tools, 'runtime_video_tools': runtime, 'credentials': keys,
            'notes': ['安装、登录、视频权限、模型资格、费用状态分别核验；unknown 不是不可用，也不是免费',
                      '系统凭据库只在显式 probe-key、选择或执行时读取；其他 Agent 的会员不会自动转成视频权限']}


def validate_selection(selection: dict) -> dict:
    spec = model_spec(selection.get('catalog_id'), selection.get('region'))
    if selection.get('version') != 1 or selection.get('provider_id') != spec['provider_id'] or selection.get('model') != spec['model']:
        raise ContractError('账号选择记录与模型目录不一致')
    if selection.get('platform') != spec['platform'] or selection.get('key_env') != spec['key_env']:
        raise ContractError('账号平台或凭据引用与模型目录不一致')
    if selection.get('confirmed_by_user') is not True:
        raise ContractError('请先由用户确认账号、模型与费用范围')
    if selection.get('subject_type') not in {'real-person', 'fictional', 'unknown'}:
        raise ContractError('请选择真人、虚构角色或未知素材类型')
    if spec['platform'] == 'alibaba':
        import re
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,62}', selection.get('workspace_id', '')):
            raise ContractError('Wan 3.0 需要所选地域的 WorkspaceId')
    return spec


def validate_subject(task: dict, provider: dict) -> None:
    model = str(provider.get('model', '')).lower()
    if 'seedance-2' not in model:
        return
    subject = task.get('subject', {})
    if subject.get('type') == 'fictional':
        if task.get('input_asset_uri'):
            raise ContractError('肖像资产不能绕过真人资格检查；请正确选择真人素材类型')
        return
    if subject.get('type') != 'real-person':
        raise ContractError('Seedance 2.0/2.5：先确认素材是否含真人人脸')
    asset = subject.get('seedance_asset', {})
    if not isinstance(asset, dict) or asset.get('verified_by_user') is not True:
        raise ContractError('Seedance 真人素材需要平台已授权肖像资产及用户确认')
    uri = asset.get('uri', '')
    if not isinstance(uri, str) or not re.fullmatch(r'asset://[A-Za-z0-9_-]+', uri):
        raise ContractError('Seedance 真人素材需要有效的 asset:// 素材 ID')
    if not recent(asset.get('verified_at', ''), seconds=86400):
        raise ContractError('Seedance 肖像资格记录已过期，请在平台重新检查')
    if asset.get('asset_status') != 'Active' or asset.get('authorization_status') != 'accepted':
        raise ContractError('Seedance 肖像必须已通过平台授权且资产状态为 Active')
    if asset.get('reference_mode_confirmed') is not True:
        raise ContractError('Seedance 真人资产使用参考图模式；请确认它不能保证逐像素保留已审批首帧')
    try:
        valid_until = datetime.fromisoformat(asset.get('valid_until', '').replace('Z', '+00:00'))
        if valid_until <= now():
            raise ValueError('expired')
    except (ValueError, TypeError):
        raise ContractError('Seedance 肖像授权已失效或缺少有效期') from None
    connection = task.get('connection_file')
    if not connection or asset.get('connection_sha256') != file_hash(Path(connection)):
        raise ContractError('Seedance 肖像资格不属于当前账号、地域和模型选择')
    if asset.get('source_sha256') != file_hash(Path(task['input_image'])):
        raise ContractError('Seedance 肖像资格不属于本次输入素材')
    if task.get('input_asset_uri') != uri:
        raise ContractError('Seedance 执行必须使用已核验素材 ID，不能直接上传本地人脸图')


def guarded(task: dict, provider: dict) -> bool:
    return bool(task.get('connection_file') or provider.get('id') in {s['provider_id'] for k, s in MODELS.items() if k != 'grok'})


def validate_execution(task: dict, provider: dict, route: dict, approval_path: Path | None) -> dict | None:
    """Called before claiming an attempt, and again by native API adapters."""
    validate_subject(task, provider)
    if not guarded(task, provider):
        return None  # Read-only compatibility with existing v0.3 task snapshots.
    if not task.get('connection_file'):
        raise ContractError('请先使用 configure_video.py select 选择账号和模型')
    connection = read_json_object(Path(task['connection_file']))
    spec = validate_selection(connection)
    if task.get('subject', {}).get('type') != connection['subject_type']:
        raise ContractError('本次任务素材类型与用户选择不一致')
    if spec['provider_id'] != provider['id'] or spec['model'] != provider.get('model') or spec['region'] != (provider.get('region') or 'global'):
        raise ContractError('执行后端、模型或地域与用户选择不一致')
    if approval_path is None:
        raise ContractError('提交生成前需要费用确认；运行 configure_video.py authorize')
    approval = read_json_object(approval_path)
    checks = {'kind': 'video-execution-approval', 'provider_id': provider['id'],
              'model': provider['model'], 'region': (provider.get('region') or 'global'),
              'task_sha256': object_sha256(task), 'route_sha256': object_sha256(route),
              'connection_sha256': file_hash(Path(task['connection_file'])),
              'credential_sha256': credential_fingerprint(connection)}
    if any(approval.get(k) != v for k, v in checks.items()) or approval.get('confirmed_by_user') is not True:
        raise ContractError('执行确认不匹配当前素材、模型、账号选择或路由')
    if not recent(approval.get('confirmed_at', '')):
        raise ContractError('费用与账号确认已超过1小时，请重新检查额度')
    billing = approval.get('billing')
    if billing == 'included-quota':
        if spec['platform'] != 'grok' or approval.get('quota_confirmed') is not True:
            raise ContractError('当前仅支持对已核验的 Grok 订阅额度确认免额外付费')
    elif billing == 'paid':
        estimated, maximum = approval.get('estimated_cost'), approval.get('max_cost')
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in [estimated, maximum]):
            raise ContractError('付费执行必须提供有效的单次估价和费用上限')
        if estimated > maximum or approval.get('currency') not in {'CNY', 'USD'} or not approval.get('price_source'):
            raise ContractError('估价超出预算或缺少币种/价格来源')
    else:
        raise ContractError('费用未知；先告知用户，不能提交生成')
    return approval
