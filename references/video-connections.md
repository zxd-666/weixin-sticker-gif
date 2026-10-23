# 视频账号、模型和费用确认

本地新增连接流程：先发现已有入口，再让用户选择账号和模型；需要 API 时隐藏输入 Key。探测和选择均不生成视频。MiniMax H3、Wan 3.0、Seedance 原生适配器依据[官方接口记录](../docs/provider-contracts-2026-10-21.md)实现，尚未使用真实 Key 实测生成。

## 可选模型

| 入口 | 具体模型 | 地域 | 图生视频请求规格 | 凭据 |
|---|---|---|---|---|
| Grok | 现有 `grok-build-local` | global | 6 秒，480p/720p | 现有 Grok 登录 |
| MiniMax H3 | `MiniMax-H3` | china / international | 4–15 秒，768p/2k | `MINIMAX_API_KEY` |
| Wan 3.0 | `wan3.0-video` | china / international | 2–30 秒，480p/720p/1080p | `DASHSCOPE_API_KEY` + WorkspaceId |
| Seedance 2.0 | `doubao-seedance-2-0-260128` | china | 4–15 秒，默认 720p | `ARK_API_KEY` + 素材资格 |
| Seedance 2.5 | `doubao-seedance-2-5-260628` | china | 4–30 秒，默认 720p | `ARK_API_KEY` + 素材资格 |

保留现有 xAI、Kling、FAL 等旧配置。新连接流程每次明确选择一个模型，关闭自动换模型和付费回退。保留模型原始视频时长；新增时长自动建立完整时长的输出档案。2 秒 Wan 素材需要同时提供适配 2 秒的动作时间线设置。微信 240×240、500KB 是交付限制，应在任务 production settings 中配置；模型输出分辨率不等于最终 GIF 尺寸。

## 1. 只读发现

使用安装项目依赖的 Python；以下命令中的 `python` 指该解释器。

```bash
python scripts/configure_video.py discover --output /absolute/work/discovery.json
python scripts/configure_video.py models
```

发现检查已知 CLI 的可执行文件、Grok 登录缓存的到期状态、Key 环境变量是否存在。Agent 可把当前可调用工具写入 `{"tools":[{"id":"实际工具名","available":true,"capabilities":["image-to-video"]}]}`，通过 `discover --tools /absolute/runtime-tools.json` 一并检查。

分别向用户展示：已安装、登录状态、视频权限、模型资格、额度/费用。缓存有效仅标为 `cached-login`，不能认定模型可用或免费。其他 Agent 的会员资格不能自动转移到视频供应商。本流程不读取浏览器 Cookie、其他应用的 Token 或全盘凭据；浏览器登录和未知工具仍由 Agent 通过当前可调用工具检查，或由用户在对应平台确认。

## 2. 用户选定后保存连接

普通用户可运行交互流程：

```bash
python scripts/configure_video.py setup --work-dir /absolute/work/connection
```

Agent 收到用户明确选择后，也可记录选择：

```bash
python scripts/configure_video.py select --model minimax-h3 --region china \
  --subject real-person --work-dir /absolute/work/connection --confirmed-by-user
# Wan 入口增加 --workspace-id <实际 WorkspaceId>；Grok 选择 --model grok --region global。
```

生成 `connection.json` 与 `selected-providers.json`，仅含非敏感配置和凭据引用。目录已有选择记录时使用新的目录，避免覆盖旧任务。

API 入口需要匹配所选地域的 Key。用户在自己的交互终端输入：

```bash
python scripts/configure_video.py configure-key --model minimax-h3 --region china
python scripts/configure_video.py probe-key --model minimax-h3 --region china
python scripts/configure_video.py probe-key --model minimax-h3 --region china --live
```

隐藏输入后保存系统凭据库；需要 `requirements.txt` 中的 keyring。仅接受 macOS Keychain、Windows、SecretService/libsecret 后端，不自动降级到明文文件。也可由用户事先在进程环境中配置相应环境变量。不要让用户在聊天、命令参数、JSON、仓库或日志中粘贴 Key。Key 配置命令仅在用户授权配置时执行。 项目当前沿用 `motion-sticker-pack.video` 作为系统凭据库的服务名称；这是查找凭据的命名空间，不是 Key，也不保存在 Skill 文件里。

默认 probe 只检查本地配置；`--live` 对 MiniMax 查询任务列表元数据，对 Wan 查询模型列表，Wan 需要 `--workspace-id`。不保留历史任务内容，不提交测试生成，不推断余额。Seedance 暂无此处已验证的 Bearer Key 只读探测接口，返回 unsupported。Grok 用户需在现有客户端确认视频功能、`/usage` 额度及额外积分设置。需要让代理环境与本次执行一致时，可用 `GROK_LEADER_SOCKET=/tmp/独立连接.sock` 指定本次进程的连接；默认仍使用现有 Grok leader，不修改全局登录或配置。

## 开源前的凭据边界

- 公开的 `SKILL.md`、README、配置样例和测试只写环境变量名或明确的模拟值；真实 Key 只由 `configure_video.py configure-key` 在交互终端隐藏输入并保存系统凭据库，或由用户预先设置进程环境变量。不要把 Key 写进 `.env.example`、命令参数、任务 JSON 或示例代码。
- `.gitignore` 排除 `.env`、本机凭据文件、`works/` 与本机生成的媒体；忽略规则不能拦住 `git add -f` 或已经进入历史的文件。公开前检查**当前 Git 跟踪文件和准备推送的全部提交历史**，只输出命中文件位置，不回显凭据。个人参考照片、任务收据和生成素材不能随 Skill 发布。
- 如果检查出真实凭据，先停止发布并在对应平台轮换；只删工作区文件不足以清除已提交历史。公开发布前核对 `origin` 指向本项目的目标仓库，避免推送到错误远端。

## 3. 准备、探测和路由

静图仍沿用原来的用户审批流程。把新连接传给原有 prepare 命令：

```bash
python scripts/prepare_workflow.py --work-dir /absolute/work/job \
  --connection /absolute/work/connection/connection.json \
  --image /absolute/approved.png --layout /absolute/layout.json \
  --prompts /absolute/prompts.json --state /absolute/job-state.json --tile-plan /absolute/tile-plan.json
python scripts/probe_video_capabilities.py --config /absolute/work/job/video-providers.json \
  --connection /absolute/work/connection/connection.json --output /absolute/work/job/capabilities.json
python scripts/route_video_provider.py --config /absolute/work/job/video-providers.json \
  --capabilities /absolute/work/job/capabilities.json --task /absolute/work/job/video-task.json \
  --output /absolute/work/job/route.json
```

`--connection` 允许能力探测器显式读取所选系统凭据库，不把值写进报告。未带此参数的旧能力探测保持只检查环境变量。`available` 仍只代表本地实现和配置齐备，服务端视频权限、余额和当前模型准入分别显示为未验证。

## 4. 额外付费先告知，用户确认后执行

向用户展示账号/地域、模型、输入图、时长、分辨率、计价来源、单次估价和预算。费用未知时停止在这里。Agent 只有收到这次费用范围的确认才能创建 approval。不得把本文中的示例数字当成当前价格，也不得自行代替用户确认。

```bash
python scripts/configure_video.py authorize --task /absolute/work/job/video-task.json \
  --route /absolute/work/job/route.json --output /absolute/work/job/execution-approval.json \
  --confirm-paid --estimated-cost <实际单次估价> --max-cost <用户同意的预算> \
  --currency CNY --price-source <已核实的价格来源> --confirmed-by-user
# 已核验且不会额外扣款的 Grok 订阅额度：用 --included-quota 替代所有付费参数。
python scripts/execute_video_route.py --config /absolute/work/job/video-providers.json \
  --task /absolute/work/job/video-task.json --route /absolute/work/job/route.json \
  --output /absolute/work/job/video-result.json --execution-approval /absolute/work/job/execution-approval.json
```

确认有效期 1 小时，绑定任务、路由、连接及 API Key 指纹；更换 Key、素材、模型或地域需重新确认；Grok 登录缓存更新后也需重新核验账号和额度。单次估价必须小于等于预算，拒绝未知、非有限或负金额。这里核对的是提交前的估价和授权范围，**不是供应商账单的硬限额**；实际费用仍以平台结算为准。API 入口按量计费，不把会员订阅自动当成 API 免费额度。

一次执行只 POST 一次，任务 ID 立即落盘。轮询超时或网络失败后，用相同任务、路由和 `--resume` 继续查询原任务，不重新 POST。提交连接中断且未拿到任务 ID 时标为不确定，先到平台查账和任务；不能盲目重提。新生成需要原有 `--retry-approval`，另有计费可能。旧 v0.3 无连接快照继续兼容原执行协议；所有新对话按本文创建带连接的任务。

## Seedance 真人素材资格

先明确 `--subject real-person|fictional|unknown`。unknown 拦截；fictional 才可按非真人路线上传。真人必须先在平台完成肖像授权、接收资产并核实 Active 状态。用户本地同意处理照片不能代替平台肖像授权。

在平台核实后制作资格 JSON（示例字段值须换为真实核验结果）：

```json
{
  "uri": "asset://具体肖像资产ID",
  "verified_by_user": true,
  "verified_at": "核验时间 ISO8601 含时区",
  "asset_status": "Active",
  "authorization_status": "accepted",
  "reference_mode_confirmed": true,
  "valid_until": "平台肖像授权截止时间 ISO8601 含时区",
  "source_sha256": "本次已审批输入 PNG 文件的 SHA256",
  "connection_sha256": "本次 connection.json 文件的 SHA256"
}
```

prepare 增加 `--portrait-asset /absolute/portrait-eligibility.json`。核验记录 24 小时内有效，授权截止时间须晚于执行时间。真人资产使用 `reference_image` 参考生成，不能保证逐像素保留已审批首帧；向用户说明并确认后才能记录 `reference_mode_confirmed: true`。任务和请求必须使用该 `asset://` ID，不能把本地真人图冒充非真人首帧。图片或账号选择不一致、未 Active、未接收授权、授权过期时均拦截。现有 Node 网关遇到真人 Seedance 2 请求时也会拦截并指向此流程。

目前资格依据用户在平台控制台核实的记录，未接入需要另行配置 AccessKey 签名的 GetAsset 实时查询，不能声称平台资格已由程序实时验证。不要写入 AccessKey、Token 或平台 Cookie。

## 验证界限

离线测试覆盖区域端点、请求与状态格式、一次 POST、超时恢复、确认绑定、预算拦截和肖像资格。真实账号权限、平台费用、模型输出质量、微信审核仍需分别验证。只有拿到视频并通过原有静图审批、背景/QC、GIF 编码检查后，才能交付为完成样片。
