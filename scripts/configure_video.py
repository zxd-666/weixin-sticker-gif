#!/usr/bin/env python3
"""Discover accounts, select a video model, configure a key, and authorize one job."""
from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

from config_contract import ContractError, object_sha256, read_json_object, validate_provider_config
from video_connections import (MODELS, credential, credential_fingerprint, discover, file_hash, model_spec,
                               save_credential, stamp, validate_execution, validate_selection)

ROOT = Path(__file__).resolve().parents[1]


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def select_model(name: str, region: str, work: Path, subject_type: str,
                 *, confirmed: bool, workspace_id: str | None = None) -> dict:
    work = work.expanduser().resolve()
    if any((work / name).exists() for name in ['connection.json', 'selected-providers.json']):
        raise ContractError('该目录已有账号选择记录；请为新选择使用独立目录')
    spec = model_spec(name, region)
    selection = {'version': 1, **spec, 'subject_type': subject_type,
                 'confirmed_by_user': confirmed, 'selected_at': stamp()}
    if workspace_id:
        selection['workspace_id'] = workspace_id
    validate_selection(selection)
    config = read_json_object(ROOT / 'assets/video-providers.example.json')
    # Make every interpreter path executable without modifying the shared template.
    for provider in config['providers']:
        command = provider.get('command', [])
        if command and command[0] == 'python3':
            command[0] = sys.executable
        for i, part in enumerate(command):
            if any(marker in part for marker in ['/absolute/path/to/weixin-sticker-gif/scripts/', '/absolute/path/to/motion-sticker-pack/scripts/']):
                command[i] = str(ROOT / 'scripts' / Path(part).name)
    if name != 'grok':
        provider = {
            'id': spec['provider_id'], 'provider': spec['platform'], 'model': spec['model'],
            'region': region, 'enabled': True, 'driver': 'command', 'priority': 100,
            'capabilities': ['image-to-video'], 'credentials': {'env': [spec['key_env']]},
            'command': [sys.executable, str(ROOT / 'scripts/native_api_video_adapter.py'),
                        '--provider-id', spec['provider_id']],
        }
        config['providers'] = [p for p in config['providers'] if p['id'] != provider['id']]
        config['providers'].append(provider)
    # Selection is explicit; choosing a model never enables a fallback purchase.
    config['routing']['fallback'] = 'none'
    validate_provider_config(config)
    work = work.expanduser().resolve()
    write(work / 'connection.json', selection)
    write(work / 'selected-providers.json', config)
    return {'connection': str(work / 'connection.json'),
            'provider_template': str(work / 'selected-providers.json'), 'selection': selection,
            'next': 'prepare_workflow.py --connection <connection.json> ...；完成路由后 authorize；不会自动生成'}


def authorize(task_path: Path, route_path: Path, output: Path, *, included: bool,
              estimated: float | None, maximum: float | None, currency: str | None,
              price_source: str | None, confirmed: bool, confirm_paid: bool) -> dict:
    if output.exists():
        raise ContractError('确认文件已存在；请使用新的输出文件，保留原有审计记录')
    task, route = read_json_object(task_path), read_json_object(route_path)
    selected = route.get('selected') or {}
    if not task.get('connection_file'):
        raise ContractError('任务缺少账号选择；请通过 --connection 重新准备本次任务')
    connection = read_json_object(Path(task['connection_file']))
    validate_selection(connection)
    if included and confirm_paid:
        raise ContractError('订阅额度与额外付费是互斥选择')
    approval = {
        'version': 1, 'kind': 'video-execution-approval', 'confirmed_at': stamp(),
        'confirmed_by_user': confirmed, 'provider_id': selected.get('id'),
        'model': selected.get('model'), 'region': (selected.get('region') or 'global'),
        'task_sha256': object_sha256(task), 'route_sha256': object_sha256(route),
        'connection_sha256': file_hash(Path(task['connection_file'])),
        'credential_sha256': credential_fingerprint(connection),
        'billing': 'included-quota' if included else 'paid' if confirm_paid else 'unknown',
        'quota_confirmed': included and confirmed, 'estimated_cost': estimated,
        'max_cost': maximum, 'currency': currency, 'price_source': price_source,
        'scope': 'one generation attempt; same-job polling resume never resubmits',
    }
    # Validate before publishing a usable approval file. Never write a partial authorization.
    import tempfile
    with tempfile.TemporaryDirectory() as temporary:
        check = Path(temporary) / 'approval.json'
        write(check, approval)
        validate_execution(task, selected, route, check)
    write(output, approval)
    return approval


def wizard(work: Path) -> dict:
    print(json.dumps(discover(), ensure_ascii=False, indent=2))
    names = list(MODELS)
    for i, name in enumerate(names, 1):
        print(f"{i}. {name} — {MODELS[name]['billing']}")
    try:
        index = int(input('选择模型编号：'))
        if not 1 <= index <= len(names):
            raise ValueError('out of range')
        name = names[index - 1]
    except (ValueError, IndexError):
        raise ContractError('模型编号无效')
    regions = MODELS[name]['regions']
    region = input(f"地域 {regions} [{regions[0]}]：").strip() or regions[0]
    spec = model_spec(name, region)
    workspace_id = input('阿里云 WorkspaceId：').strip() if name == 'wan3' else None
    if spec['key_env'] and not credential(name, region):
        print(f"未找到 {spec['key_env']}。Key 将存入系统凭据库，不写项目文件。")
        if not sys.stdin.isatty():
            raise ContractError('Key 配置需要交互终端，防止输入回显')
        save_credential(name, region, getpass.getpass('API Key（隐藏输入）：'))
    subject_type = {'1': 'real-person', '2': 'fictional', '3': 'unknown'}.get(
        input('素材类型：1 真人 / 2 虚构角色 / 3 未确定：').strip(), 'unknown')
    if name == 'grok':
        print('请在 Grok /usage 检查视频权限、现有额度和额外积分设置。安装/登录缓存不等于可生成。')
    else:
        print('这是按量计费入口。选择模型不会提交生成；路由后还需确认估价和费用上限。')
    if input('确认使用上述账号、地域与模型？输入 确认：').strip() != '确认':
        raise ContractError('用户未确认选择，未创建连接或生成任务')
    return select_model(name, region, work, subject_type, confirmed=True, workspace_id=workspace_id)


def main() -> int:
    parser = argparse.ArgumentParser(description='视频账号探测、模型选择和安全 Key 配置（默认不生成）')
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('discover', help='只读探测已知 CLI、登录缓存、环境变量和运行时视频工具')
    p.add_argument('--tools', type=Path)
    p.add_argument('--output', type=Path)
    sub.add_parser('models', help='查看模型、地域、分辨率和计费类型')
    p = sub.add_parser('setup', help='交互式发现、选择和 Key 配置')
    p.add_argument('--work-dir', type=Path, required=True)
    p = sub.add_parser('select', help='Agent 在收到用户确认后记录明确选择')
    p.add_argument('--model', choices=MODELS, required=True)
    p.add_argument('--region', required=True)
    p.add_argument('--work-dir', type=Path, required=True)
    p.add_argument('--workspace-id')
    p.add_argument('--subject', choices=['real-person', 'fictional', 'unknown'], required=True)
    p.add_argument('--confirmed-by-user', action='store_true', required=True)
    for action in ['configure-key', 'probe-key']:
        p = sub.add_parser(action, help='隐藏输入保存系统凭据库' if action == 'configure-key' else '显式读取凭据；--live 仅查询只读元数据')
        p.add_argument('--model', choices=[k for k in MODELS if k != 'grok'], required=True)
        p.add_argument('--region', required=True)
        if action == 'probe-key':
            p.add_argument('--live', action='store_true')
            p.add_argument('--workspace-id')
    p = sub.add_parser('authorize', help='绑定当前任务和路由，确认一次生成的费用范围')
    p.add_argument('--task', type=Path, required=True)
    p.add_argument('--route', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--included-quota', action='store_true')
    p.add_argument('--confirm-paid', action='store_true')
    p.add_argument('--estimated-cost', type=float)
    p.add_argument('--max-cost', type=float)
    p.add_argument('--currency', choices=['CNY', 'USD'])
    p.add_argument('--price-source')
    p.add_argument('--confirmed-by-user', action='store_true', required=True)
    args = parser.parse_args()
    if args.action == 'models':
        result = MODELS
    elif args.action == 'discover':
        result = discover(read_json_object(args.tools) if args.tools else None)
        if args.output:
            write(args.output, result)
    elif args.action == 'setup':
        result = wizard(args.work_dir)
    elif args.action == 'select':
        result = select_model(args.model, args.region, args.work_dir, args.subject,
                              confirmed=args.confirmed_by_user, workspace_id=args.workspace_id)
    elif args.action == 'configure-key':
        if not sys.stdin.isatty():
            raise ContractError('请在交互终端隐藏输入 Key；不会接受命令行 Key 或回显输入')
        save_credential(args.model, args.region, getpass.getpass('API Key（隐藏输入，保存系统凭据库）：'))
        result = {'configured': True, 'storage': 'system-keychain', 'generation_performed': False}
    elif args.action == 'probe-key':
        key = credential(args.model, args.region)
        result = {'configured': bool(key), 'generation_unverified': True, 'balance': 'unknown'}
        if args.live and key:
            from native_api_video_adapter import probe_metadata
            result.update(probe_metadata(model_spec(args.model, args.region), key, args.workspace_id))
    else:
        result = authorize(args.task, args.route, args.output, included=args.included_quota,
                           estimated=args.estimated_cost, maximum=args.max_cost, currency=args.currency,
                           price_source=args.price_source, confirmed=args.confirmed_by_user,
                           confirm_paid=args.confirm_paid)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ContractError, OSError, EOFError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
