[原项目：ChenAI-TGF/SnapTranslate](https://github.com/ChenAI-TGF/SnapTranslate)

# SnapTranslate-Lite

SnapTranslate-Lite 是面向 Windows 10/11 64 位的精简翻译工具。项目基于原版 SnapTranslate 修改，只保留划词翻译和本地截图 OCR 翻译，不保存翻译历史。

当前版本：`v1.0.0`

## 功能

- 划词翻译：选中文字后按 `Ctrl+L`。
- 实时翻译：鼠标左键拖选文字并松开后自动翻译，默认关闭，可用 `Ctrl+Alt+L` 切换。
- 截图翻译：按 `Tab+Q`，在鼠标所在的当前显示器内框选文字；OCR 截图不会上传。
- 自动最优：并发尝试内置翻译源，返回首个有效结果；也可只用 MyMemory。
- 输出效果：可设置显示时长、原文与译文/只显示译文、悬浮背景颜色，以及蓝、绿、紫、红、黄色或无边框。
- 托盘运行：关闭设置窗口后进入系统托盘，可再次打开设置或退出程序。
- 静默启动：开启后，下次运行 EXE 直接进入托盘。

## 与原项目的区别

本项目移除了生词本、生词回顾、历史记录、自动朗读、网页服务等功能，保留并调整了划词翻译，同时加入了适合短文本的本地 OCR、实时翻译、混合 DPI 适配和托盘设置。

## 使用方法

1. 从 [Releases](../../releases) 下载 `SnapTranslate.exe` 并运行。
2. 在设置窗口选择翻译源、快捷键和输出效果，保存后关闭窗口即可后台运行。
3. 双击托盘图标或选择“打开设置”可再次进入设置；请选择托盘菜单中的“退出”来结束程序。

## 注意事项

- 单次输入最多 120 个字符，超过后会提示，不会自动截断。
- 翻译需要联网，选中的文字或 OCR 结果会发送给所选翻译服务；OCR 图片只在本地处理。
- 划词翻译会临时发送 `Ctrl+C` 读取选区，然后恢复剪贴板的当前内容。程序不会读取或复制完整的 `Win+V` 历史列表，但 Windows 仍可能把临时复制项写入历史。
- 实时翻译优先使用 Windows UI Automation 判断文字选区，不支持时才使用光标状态和剪贴板兜底。普通点击、右键和键盘选区不会触发。
- OCR 适合少量中、英、日等屏幕文字，不适合表格、公式、手写体或完整文档版面；识别过程中不显示识别中提示。
- 程序只在 Windows 明确报告独占 Direct3D 全屏时暂停快捷键与实时翻译，退出后自动恢复。
- OCR 和设置窗口使用物理坐标与动态 DPI 适配，支持 100%/200% 等不同缩放比例。悬浮窗采用约 8 个逻辑像素圆角和克制的非线性柔光；96 DPI 下设置窗口默认约为 384×558。
- 配置保存在 `%APPDATA%\SnapTranslate\settings.json`。配置版本与程序版本不一致时会自动重建。
- 本程序未签名，Windows SmartScreen 可能在首次运行时提示风险，请确认文件来自本项目 Release。

## 从源码运行

需要 Python 3.12 64 位：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run_snaptranslate.py
```

打包单文件 EXE：

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller==6.16.0
.\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm SnapTranslate.spec
```

第三方组件和 OCR 模型来源见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 与 [MODEL_PROVENANCE.md](assets/models/MODEL_PROVENANCE.md)。

## 免责声明

本项目基于原版 SnapTranslate 修改，仅供学习和个人效率使用。翻译服务、模型服务及公开接口可能受到网络、额度、服务规则和地区政策影响，使用前请自行确认合规性与可能产生的费用。开发者不保证所有服务长期可用，也不对因使用本程序造成的损失负责。

原项目当前未提供许可证文件。本仓库以 GitHub Fork 形式保留来源关系；除 GitHub 平台允许的查看与 Fork 外，不代表获得额外的复制、分发或商业使用授权。
