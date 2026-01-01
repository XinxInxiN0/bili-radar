# 麦哔雷达 (MaiBot Bili Radar)

> Bilibili UP 主新视频推送插件，支持群内订阅管理

## 功能特性

- 🎯 **订阅管理**：群内通过 `/radar` 指令添加/删除/查看订阅
- 📡 **自动推送**：后台轮询检测新视频，自动推送到订阅群
- 🔒 **去重保证**：每个视频对同一群仅推送一次
- 💾 **持久化存储**：订阅关系和去重状态数据库持久化
- ⚙️ **配置化**：轮询间隔、推送模板、权限控制等均可配置

## 快速开始

### 安装

将插件放置在 MaiBot 的 `plugins/` 目录下，重启 MaiBot 即可自动加载。

### 配置

插件首次加载时会自动生成配置项，可在 MaiBot 配置文件中修改：

```yaml
maibot-bili-radar:
  polling:
    interval_seconds: 120  # 轮询间隔（秒）
    max_concurrency: 3     # 最大并发请求数
  
  bilibili:
    timeout_seconds: 10
    user_agent: "Mozilla/5.0 ..."
    referer: "https://www.bilibili.com"
    wbi_keys_refresh_hours: 12
  
  push:
    message_template: "🎬 新视频推送\n标题：{title}\n作者：{author}\n链接：{url}"
  
  permission:
    admin_only: true  # 是否仅管理员可修改订阅
    operator_allowlist: []
```

## 指令说明

所有指令均以 `/radar` 开头：

| 指令 | 参数 | 功能 | 权限要求 |
|------|------|------|----------|
| `/radar add` | `<mid>` | 添加订阅（mid 为 UP 主 ID） | 管理员/白名单 |
| `/radar del` | `<mid>` | 删除订阅 | 管理员/白名单 |
| `/radar list` | - | 列出本群所有订阅 | 所有人 |
| `/radar on` | `<mid>` | 启用推送 | 管理员/白名单 |
| `/radar off` | `<mid>` | 禁用推送（保留订阅） | 管理员/白名单 |
| `/radar test` | `<mid>` | 立即测试推送最新视频 | 管理员/白名单 |
| `/radar help` | - | 显示帮助信息 | 所有人 |

### 使用示例

```bash
# 添加订阅（以 UP 主 UID 546195 为例）
/radar add 546195

# 查看本群订阅
/radar list

# 测试推送
/radar test 546195

# 临时关闭推送（不删除订阅）
/radar off 546195

# 删除订阅
/radar del 546195
```

## 工作原理

1. **订阅管理**：用户通过群指令添加订阅，插件记录 `(stream_id, mid)` 关系
2. **后台轮询**：定时任务按配置的间隔轮询所有订阅的 UP 主
3. **新视频检测**：对比最新视频的 `bvid` 和 `created_ts` 与数据库记录
4. **推送与去重**：检测到新视频后推送到订阅群，并更新去重状态

## 技术细节

### 数据结构

- **订阅表** `bili_subscription`：存储订阅关系和去重状态
- **双条件去重**：同时比对 `bvid` 和 `created_ts`，避免 UP 删除重发导致的误判

### WBI 签名

使用 Bilibili Web 端 WBI 签名机制，自动获取和刷新签名密钥：
- 密钥缓存：默认 12 小时刷新
- 失败重试：签名失败时自动刷新密钥并重试

### 错误处理

- **-412 风控拦截**：记录日志并跳过当前周期
- **网络超时**：配置超时时间，失败不阻塞其他 UP 的检查
- **API 变更**：完善日志记录，快速定位问题

## 常见问题

### Q: 如何获取 UP 主的 mid？

A: 访问 UP 主主页，URL 中的数字即为 mid。例如 `https://space.bilibili.com/546195` 中的 `546195`。

### Q: 轮询间隔设多少合适？

A: 默认 120 秒，订阅量大时可适当增加避免触发风控。建议不低于 60 秒。

### Q: 添加订阅后会推送历史视频吗？

A: 不会。添加订阅时仅记录当前最新视频作为基准，后续仅推送新发布的视频。

### Q: 遇到 -412 错误怎么办？

A: 这是 Bilibili 的风控拦截。插件会自动跳过当前周期，可尝试：
- 增加轮询间隔
- 减少同时订阅的 UP 数量
- 配置 Cookie（可选的 `cookie_sessdata`）

## 开发与贡献

### 项目结构

```
maibot-bili-radar/
├── _manifest.json       # 插件清单
├── plugin.py            # 插件主入口
├── models.py            # 数据库模型
├── bili/                # Bilibili API 客户端
│   ├── wbi_signer.py    # WBI 签名器
│   ├── client.py        # API 客户端
│   └── parser.py        # 数据解析器
├── commands/            # 群指令
│   ├── base.py          # 基础工具
│   ├── subscription.py  # 订阅管理指令
│   └── utils.py         # 工具指令
└── tasks/               # 后台任务
    └── polling_task.py  # 轮询任务
```

### 技术栈

- Python 3.8+
- Peewee ORM（数据库）
- MaiBot Plugin System
- Bilibili WBI API

## 许可证

MIT License - 详见 [LICENSE](LICENSE)

## 致谢

- [Bilibili-API-collect](https://github.com/SocialSisterYi/bilibili-API-collect) - API 文档参考
- [MaiBot](https://docs.mai-mai.org/) - 插件框架

---

**注意**：本插件仅用于学习和个人使用，请勿滥用。使用时请遵守 Bilibili 服务条款。
