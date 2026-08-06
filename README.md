# Clipboard Workspace

专为 macOS 打造的本地剪贴板工作台：管理复制内容、实时搜索、快速粘贴（⌘⇧V）、
收藏夹、代码片段、快捷 Action —— 全部数据本地存储，不上传。

- **需求文档**：[Clipboard Workspace.md](Clipboard%20Workspace.md)
- **开发文档**（架构/打包/TCC 权限/性能）：[DEVELOPMENT.md](DEVELOPMENT.md)

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

## 项目结构

```
app/          入口与生命周期（懒加载装配，保证启动 <1s）
actions/      Action 插件体系（每个 .py 一个 Action，主程序不写死；已内置 11 个）
database/     SQLite + WAL（SQLAlchemy ORM + 轻量迁移）
services/     剪贴板监听 / 全局热键 / 搜索(FTS5) / Snippet / Action / 图片
ui/           PySide6 视图（主窗口 / Quick Paste / 各页面）
config/       默认配置与用户覆盖（YAML）
packaging/    PyInstaller 打包 + 自签名签名管线
```

## 打包

```bash
bash packaging/make_cert.sh   # 每台机器一次：自签名证书
bash packaging/build.sh       # 打包 + 签名 + 验证
```

> 打包权限要点（详见 DEVELOPMENT.md §5）：**绝不用 ad-hoc 签名**，
> 否则 TCC 授权（辅助功能）会随每次构建重建而失效。

## 状态

骨架已就绪（V0.1.0）。待实现见 [DEVELOPMENT.md §11 下一步 TODO](DEVELOPMENT.md)。
