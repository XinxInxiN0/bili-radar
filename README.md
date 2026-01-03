# 麦哔雷达 (MaiBot Bili Radar)

> Bilibili UP 主新视频推送插件，支持群内订阅管理

## 功能特性

- 🎯 **订阅管理**：群内通过 `/radar` 指令添加/删除/查看订阅
- 📡 **自动推送**：后台轮询检测新视频，自动推送到订阅群
- 🔒 **去重保证**：每个视频对同一群仅推送一次
- 💾 **持久化存储**：订阅关系和去重状态数据库持久化
- 🛡️ **健壮性优化**：记录稳定平台 ID，推送失败时自动找回活跃聊天流
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

```


## 致谢

- [Bilibili-API-collect](https://github.com/SocialSisterYi/bilibili-API-collect) - Bilibili API
- [MaiBot](https://docs.mai-mai.org/) - 麦麦

---

**注意**：本插件仅用于学习和个人使用，请勿滥用。使用时请遵守 Bilibili 服务条款。
