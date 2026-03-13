# 🎮 Unity Prefab Text Extractor

一个用于 Unity 项目本地化的文本提取与管理工具。支持从 Prefab 文件中扫描、提取、翻译文本，并自动生成本地化 Key。

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![Platform](https://img.shields.io/badge/Platform-Windows-green.svg)
![Unity](https://img.shields.io/badge/Unity-Compatible-orange.svg)
![GitHub stars](https://img.shields.io/github/stars/EthanJ-Sss/transify?style=social)

⭐ 当前 Star：1（已接入动态徽章，后续会自动更新）

## ✨ 功能特性

### 📤 扫描 & 导出
- 递归扫描 Unity 项目中的 `.prefab` 文件
- 自动识别 **Text (Legacy)** 和 **TextMeshPro (TMP)** 组件
- 提取所有文本内容并导出为 CSV 格式
- 支持按名称筛选 Prefab 文件

### 🔑 加 KEY
- 自动为文本生成本地化 Key
- 支持复用已有 Key（通过 LocIndex 匹配）
- 内置中英文翻译词典
- 支持 GPT API 智能翻译（可配置）

### 📥 导入 & 应用
- 将翻译后的 Key 写回 Prefab 文件
- 自动添加 LocComponent 组件
- 支持 Perforce (P4) 自动 Checkout

## 🚀 快速开始

### 环境要求
- Python 3.8 或更高版本
- Windows 操作系统

### 安装依赖
```bash
pip install requests
```

### 运行工具
**方式一：双击运行**
```
双击 run.bat
```

**方式二：命令行运行**
```bash
python ExtractPrefabText.py
```

## 📖 使用说明

### 1. 扫描 & 导出文本

1. 在「扫描 & 导出」页面设置 **扫描目录**（Unity 项目的 Assets 文件夹）
2. 设置 **导出目录**（CSV 输出位置）
3. 点击「刷新 Prefab 列表」扫描所有 Prefab 文件
4. 选择需要处理的文件（可全选或按筛选条件选择）
5. 点击「🚀 扫描并导出」

导出的 CSV 包含以下字段：
| 字段 | 说明 |
|------|------|
| Prefab Path | Prefab 相对路径 |
| GameObject Name | 游戏对象名称 |
| GameObject ID | 对象唯一 ID |
| Original Text | 原始文本内容 |
| KeyId | 本地化 Key（如已存在） |

### 2. 生成本地化 Key

1. 切换到「加 KEY」页面
2. 选择待处理的 CSV 文件
3. 配置 LocIndex 文件（用于复用已有 Key）
4. 设置 Key 前缀（如 `T_`、`UI_`）
5. 点击「🔑 生成 Key 并导出」

工具会：
- 自动匹配已有 Key（避免重复）
- 为新文本生成语义化 Key
- 使用 GPT 进行中英翻译（可选）

### 3. 应用到 Prefab

1. 切换到「导入 & 应用」页面
2. 选择包含 KeyId 的 CSV 文件
3. 可选：启用 P4 Checkout
4. 点击「🔧 应用到 Prefab」

## ⚙️ 配置说明

### LocComponent GUID
在「设置」页面配置你项目中 LocComponent 脚本的 GUID。可在脚本的 `.meta` 文件中找到：

```yaml
guid: 38e26ec42db775e4faeb63f8c5858bec
```

### GPT 翻译配置
支持配置 OpenAI 兼容的 API 进行智能翻译：
- **API URL**: API 端点地址
- **API Key**: 认证密钥
- **Model**: 模型名称（如 `gpt-4o`、`gpt-3.5-turbo`）

## 📁 文件结构

```
transify/
├── ExtractPrefabText.py      # 主程序
├── run.bat                   # Windows 启动脚本
├── prefab_tool_config.json   # 配置文件（自动生成）
├── LocIndex.csv              # 本地化索引（可选）
└── TextExport/               # 导出目录
    ├── PrefabExport_*.csv           # 扫描导出文件
    ├── PrefabExport_WithKeys_*.csv  # 带 Key 的导出文件
    └── NewKeys/
        └── NewKeys_Entities_*.csv   # 新增 Key 列表
```

## 🎨 界面预览

工具采用现代深色主题设计，包含以下标签页：
- 📤 **扫描 & 导出** - 扫描 Prefab 并导出文本
- 🔑 **加 KEY** - 生成本地化 Key
- 📥 **导入 & 应用** - 将 Key 写回 Prefab
- ⚙️ **设置** - 配置 LocComponent GUID 等

## 🔧 技术细节

### 支持的组件类型
- Unity Text (Legacy): `m_Text` 属性
- TextMeshPro: `m_text` 属性

### YAML 解析
工具使用自定义 YAML 解析器处理 Unity Prefab 文件格式，支持：
- 对象引用解析
- 组件关系追踪
- 安全的文件修改

## 📝 注意事项

1. **备份重要文件** - 修改 Prefab 前建议先备份
2. **P4 集成** - 使用 Perforce 时确保已安装 p4 命令行工具
3. **编码格式** - CSV 使用 UTF-8 with BOM 编码
4. **Unity 版本** - 兼容 Unity 2019.4 及以上版本

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

### Contributors

- [@EthanJ-Sss](https://github.com/EthanJ-Sss)（3 contributions）
- [@altairshi-GD](https://github.com/altairshi-GD)（1 contribution）

## 📄 License

MIT License
