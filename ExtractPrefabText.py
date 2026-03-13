import os
import sys
import re
import json
import csv
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import threading
from datetime import datetime
import shutil
import subprocess

# HTTP请求支持
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# --- Configuration ---
CONFIG_FILE = "prefab_tool_config.json"
DEFAULT_LOC_GUID = "38e26ec42db775e4faeb63f8c5858bec"  # Default LocComponent GUID
DEFAULT_TRANSIFY_URL = "https://transify.garena.com"
DEFAULT_TRANSIFY_RESOURCE_ID = "4209"  # 默认资源ID


class UnityYAMLParser:
    """
    A simple parser for Unity YAML files to handle GameObject/Component relationships.
    """
    def __init__(self, file_path):
        self.file_path = file_path
        self.objects = {}
        self.lines = []

    def parse(self):
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                self.lines = f.readlines()
        except UnicodeDecodeError:
            with open(self.file_path, 'r', encoding='latin-1') as f:
                self.lines = f.readlines()
        
        current_obj = None
        header_pattern = re.compile(r'^--- !u!(\d+) &(\d+)')
        
        for i, line in enumerate(self.lines):
            match = header_pattern.match(line)
            if match:
                if current_obj:
                    current_obj['line_end'] = i
                
                class_id = int(match.group(1))
                file_id = match.group(2)
                
                current_obj = {
                    'class_id': class_id,
                    'file_id': file_id,
                    'line_start': i,
                    'line_end': -1,
                    'lines_raw': []
                }
                self.objects[file_id] = current_obj
            
            if current_obj:
                current_obj['lines_raw'].append(line)

        if current_obj:
            current_obj['line_end'] = len(self.lines)

    def find_component_by_guid(self, game_object_id, guid):
        """Check if GameObject has a MonoBehaviour with specific Script GUID"""
        go = self.objects.get(game_object_id)
        if not go or go['class_id'] != 1:
            return None
            
        components = []
        in_components = False
        for line in go['lines_raw']:
            if "m_Component:" in line:
                in_components = True
                continue
            if in_components:
                if line.strip().startswith("- component:"):
                    match = re.search(r'fileID: (\d+)', line)
                    if match:
                        components.append(match.group(1))
                elif not line.startswith(" ") and ":" in line:
                    in_components = False

        for comp_id in components:
            comp = self.objects.get(comp_id)
            if comp and comp['class_id'] == 114:
                for l in comp['lines_raw']:
                    if "m_Script:" in l and guid in l:
                        return comp
        return None

    def get_property(self, obj_id, prop_name):
        obj = self.objects.get(obj_id)
        if not obj:
            return None
        for line in obj['lines_raw']:
            if f"{prop_name}:" in line:
                return line.split(":", 1)[1].strip()
        return None
        
    def get_string_id_from_loc(self, loc_comp):
        for line in loc_comp['lines_raw']:
            if "StringID:" in line:
                val = line.split("StringID:", 1)[1].strip()
                if val.startswith('"') and val.endswith('"'):
                    return val[1:-1]
                return val
        return ""


class ModernStyle:
    """Modern UI styling constants"""
    BG_PRIMARY = "#1e1e2e"
    BG_SECONDARY = "#2d2d3f"
    BG_TERTIARY = "#3d3d5c"
    ACCENT = "#7c3aed"
    ACCENT_HOVER = "#8b5cf6"
    TEXT_PRIMARY = "#e2e2e9"
    TEXT_SECONDARY = "#a0a0b0"
    SUCCESS = "#10b981"
    WARNING = "#f59e0b"
    ERROR = "#ef4444"
    BORDER = "#4a4a6a"


class PrefabTextExtractor:
    def __init__(self, root):
        self.root = root
        self.root.title("Unity Prefab Text Extractor")
        self.root.geometry("1100x800")
        self.root.minsize(900, 600)
        
        # Configure dark theme
        self.root.configure(bg=ModernStyle.BG_PRIMARY)
        self.setup_styles()
        
        # Variables
        self.scan_dir = tk.StringVar()
        self.export_dir = tk.StringVar()
        self.import_file = tk.StringVar()
        self.loc_guid = tk.StringVar(value=DEFAULT_LOC_GUID)
        self.p4_enabled = tk.BooleanVar(value=False)
        self.recursive_scan = tk.BooleanVar(value=True)
        
        # Add Key variables
        self.addkey_input_file = tk.StringVar()
        self.addkey_ref_file = tk.StringVar()
        self.key_prefix = tk.StringVar(value="T_")
        
        # Transify variables
        self.transify_url = tk.StringVar(value=DEFAULT_TRANSIFY_URL)
        self.transify_resource_id = tk.StringVar(value=DEFAULT_TRANSIFY_RESOURCE_ID)
        self.transify_cookie = tk.StringVar()
        self.last_exported_entities_file = None  # 最后导出的entities文件路径
        
        # GPT API variables - 默认配置
        self.DEFAULT_GPT_API_URL = "https://llm-gateway.staging.id.gametech.garenanow.com/v1"
        self.DEFAULT_GPT_API_KEY = "sk-3-1qq3u2ZCNT6BGRQiAmlw"
        self.DEFAULT_GPT_MODEL = "gpt-4o"
        
        self.gpt_api_url = tk.StringVar(value=self.DEFAULT_GPT_API_URL)
        self.gpt_api_key = tk.StringVar(value=self.DEFAULT_GPT_API_KEY)
        self.gpt_model = tk.StringVar(value=self.DEFAULT_GPT_MODEL)
        self.use_gpt_translation = tk.BooleanVar(value=True)  # 默认启用GPT翻译
        self.translation_cache = {}  # 翻译缓存，避免重复调用
        
        # Data
        self.all_prefabs = []
        self.prefab_map = {}
        self.selected_prefabs = set()
        self.scan_results = []
        self.existing_keys = set()  # 已存在的Key集合
        self.loc_index_map = {}  # 英文内容 -> KeyId 的映射 (用于复用已有Key)
        
        # LocIndex文件 - 默认使用当前目录下的LocIndex.csv
        self.DEFAULT_LOC_INDEX_FILE = os.path.join(os.getcwd(), "LocIndex.csv")
        self.loc_index_file = tk.StringVar(value=self.DEFAULT_LOC_INDEX_FILE if os.path.exists(self.DEFAULT_LOC_INDEX_FILE) else "")
        
        self.load_config()
        self.setup_ui()
        
        # 自动加载LocIndex
        if self.loc_index_file.get() and os.path.exists(self.loc_index_file.get()):
            self.load_loc_index()
        
    def setup_styles(self):
        """Configure ttk styles for modern dark theme"""
        style = ttk.Style()
        style.theme_use('clam')
        
        # Frame styles
        style.configure("Dark.TFrame", background=ModernStyle.BG_PRIMARY)
        style.configure("Card.TFrame", background=ModernStyle.BG_SECONDARY)
        
        # Label styles
        style.configure("Dark.TLabel", 
                       background=ModernStyle.BG_PRIMARY, 
                       foreground=ModernStyle.TEXT_PRIMARY,
                       font=("Segoe UI", 10))
        style.configure("Header.TLabel", 
                       background=ModernStyle.BG_PRIMARY, 
                       foreground=ModernStyle.TEXT_PRIMARY,
                       font=("Segoe UI", 14, "bold"))
        style.configure("Card.TLabel", 
                       background=ModernStyle.BG_SECONDARY, 
                       foreground=ModernStyle.TEXT_PRIMARY,
                       font=("Segoe UI", 10))
        
        # Button styles
        style.configure("Accent.TButton",
                       background=ModernStyle.ACCENT,
                       foreground="white",
                       font=("Segoe UI", 10, "bold"),
                       padding=(20, 10))
        style.map("Accent.TButton",
                 background=[("active", ModernStyle.ACCENT_HOVER)])
        
        style.configure("Secondary.TButton",
                       background=ModernStyle.BG_TERTIARY,
                       foreground=ModernStyle.TEXT_PRIMARY,
                       font=("Segoe UI", 9),
                       padding=(10, 5))
        
        # Entry styles
        style.configure("Dark.TEntry",
                       fieldbackground=ModernStyle.BG_TERTIARY,
                       foreground=ModernStyle.TEXT_PRIMARY,
                       insertcolor=ModernStyle.TEXT_PRIMARY)
        
        # Checkbutton
        style.configure("Dark.TCheckbutton",
                       background=ModernStyle.BG_SECONDARY,
                       foreground=ModernStyle.TEXT_PRIMARY,
                       font=("Segoe UI", 10))
        
        # Notebook
        style.configure("Dark.TNotebook", 
                       background=ModernStyle.BG_PRIMARY,
                       borderwidth=0)
        style.configure("Dark.TNotebook.Tab",
                       background=ModernStyle.BG_TERTIARY,
                       foreground=ModernStyle.TEXT_PRIMARY,
                       padding=(20, 10),
                       font=("Segoe UI", 10, "bold"))
        style.map("Dark.TNotebook.Tab",
                 background=[("selected", ModernStyle.ACCENT)],
                 foreground=[("selected", "white")])
        
        # Treeview
        style.configure("Dark.Treeview",
                       background=ModernStyle.BG_SECONDARY,
                       foreground=ModernStyle.TEXT_PRIMARY,
                       fieldbackground=ModernStyle.BG_SECONDARY,
                       borderwidth=0,
                       font=("Consolas", 9))
        style.configure("Dark.Treeview.Heading",
                       background=ModernStyle.BG_TERTIARY,
                       foreground=ModernStyle.TEXT_PRIMARY,
                       font=("Segoe UI", 10, "bold"))
        style.map("Dark.Treeview",
                 background=[("selected", ModernStyle.ACCENT)])
        
        # Progressbar
        style.configure("Accent.Horizontal.TProgressbar",
                       background=ModernStyle.ACCENT,
                       troughcolor=ModernStyle.BG_TERTIARY)
        
        # LabelFrame
        style.configure("Card.TLabelframe",
                       background=ModernStyle.BG_SECONDARY,
                       foreground=ModernStyle.TEXT_PRIMARY)
        style.configure("Card.TLabelframe.Label",
                       background=ModernStyle.BG_SECONDARY,
                       foreground=ModernStyle.ACCENT,
                       font=("Segoe UI", 11, "bold"))

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.scan_dir.set(config.get('scan_dir', ''))
                    self.export_dir.set(config.get('export_dir', ''))
                    self.loc_guid.set(config.get('loc_guid', DEFAULT_LOC_GUID))
                    self.p4_enabled.set(config.get('p4_enabled', False))
                    # Transify config
                    self.transify_url.set(config.get('transify_url', DEFAULT_TRANSIFY_URL))
                    self.transify_resource_id.set(config.get('transify_resource_id', DEFAULT_TRANSIFY_RESOURCE_ID))
                    self.transify_cookie.set(config.get('transify_cookie', ''))
                    # LocIndex config - 如果为空使用默认路径
                    loc_file = config.get('loc_index_file', '')
                    if loc_file and os.path.exists(loc_file):
                        self.loc_index_file.set(loc_file)
                    elif os.path.exists(self.DEFAULT_LOC_INDEX_FILE):
                        self.loc_index_file.set(self.DEFAULT_LOC_INDEX_FILE)
                    # GPT API config
                    # GPT配置：如果配置文件中的值为空，使用默认值
                    gpt_url = config.get('gpt_api_url', '')
                    gpt_key = config.get('gpt_api_key', '')
                    gpt_model = config.get('gpt_model', '')
                    self.gpt_api_url.set(gpt_url if gpt_url else self.DEFAULT_GPT_API_URL)
                    self.gpt_api_key.set(gpt_key if gpt_key else self.DEFAULT_GPT_API_KEY)
                    self.gpt_model.set(gpt_model if gpt_model else self.DEFAULT_GPT_MODEL)
                    self.use_gpt_translation.set(config.get('use_gpt_translation', True))
            except Exception as e:
                print(f"Failed to load config: {e}")
        
        # Set default export dir if empty
        if not self.export_dir.get():
            self.export_dir.set(os.path.join(os.getcwd(), "TextExport"))

    def save_config(self):
        config = {
            'scan_dir': self.scan_dir.get(),
            'export_dir': self.export_dir.get(),
            'loc_guid': self.loc_guid.get(),
            'p4_enabled': self.p4_enabled.get(),
            # Transify config
            'transify_url': self.transify_url.get(),
            'transify_resource_id': self.transify_resource_id.get(),
            'transify_cookie': self.transify_cookie.get(),
            # LocIndex config
            'loc_index_file': self.loc_index_file.get(),
            # GPT API config
            'gpt_api_url': self.gpt_api_url.get(),
            'gpt_api_key': self.gpt_api_key.get(),
            'gpt_model': self.gpt_model.get(),
            'use_gpt_translation': self.use_gpt_translation.get()
        }
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Failed to save config: {e}")

    def setup_ui(self):
        # Main container
        main_frame = ttk.Frame(self.root, style="Dark.TFrame")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)
        
        # Header
        header_frame = ttk.Frame(main_frame, style="Dark.TFrame")
        header_frame.pack(fill=tk.X, pady=(0, 15))
        
        ttk.Label(header_frame, text="🎮 Unity Prefab Text Extractor", 
                 style="Header.TLabel").pack(side=tk.LEFT)
        ttk.Label(header_frame, text="通用版本 - 适用于任意Unity项目", 
                 style="Dark.TLabel").pack(side=tk.RIGHT)
        
        # Notebook for tabs
        notebook = ttk.Notebook(main_frame, style="Dark.TNotebook")
        notebook.pack(fill=tk.BOTH, expand=True)
        
        # Tab 1: Scan & Export
        export_tab = ttk.Frame(notebook, style="Dark.TFrame")
        notebook.add(export_tab, text="📤 扫描 & 导出")
        self.setup_export_tab(export_tab)
        
        # Tab 2: Add Keys
        addkey_tab = ttk.Frame(notebook, style="Dark.TFrame")
        notebook.add(addkey_tab, text="🔑 加KEY")
        self.setup_addkey_tab(addkey_tab)
        
        # Tab 3: Import & Patch
        import_tab = ttk.Frame(notebook, style="Dark.TFrame")
        notebook.add(import_tab, text="📥 导入 & 应用")
        self.setup_import_tab(import_tab)
        
        # Tab 4: Settings
        settings_tab = ttk.Frame(notebook, style="Dark.TFrame")
        notebook.add(settings_tab, text="⚙️ 设置")
        self.setup_settings_tab(settings_tab)
        
        # Log Panel (shared)
        log_frame = ttk.LabelFrame(main_frame, text="📋 日志", style="Card.TLabelframe", padding=10)
        log_frame.pack(fill=tk.BOTH, expand=False, pady=(15, 0))
        
        self.log_text = tk.Text(log_frame, height=8, 
                               bg=ModernStyle.BG_TERTIARY, 
                               fg=ModernStyle.TEXT_PRIMARY,
                               insertbackground=ModernStyle.TEXT_PRIMARY,
                               font=("Consolas", 9),
                               relief=tk.FLAT,
                               padx=10, pady=10)
        self.log_text.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=scrollbar.set)
        
        # Progress bar
        self.progress = ttk.Progressbar(main_frame, mode='determinate', 
                                        style="Accent.Horizontal.TProgressbar")
        self.progress.pack(fill=tk.X, pady=(10, 0))
        
        # Status bar
        self.status_var = tk.StringVar(value="就绪")
        status_bar = ttk.Label(main_frame, textvariable=self.status_var, style="Dark.TLabel")
        status_bar.pack(fill=tk.X, pady=(5, 0))

    def setup_export_tab(self, parent):
        # Path selection frame
        path_frame = ttk.LabelFrame(parent, text="📁 路径配置", style="Card.TLabelframe", padding=15)
        path_frame.pack(fill=tk.X, padx=10, pady=10)
        
        # Scan directory
        row1 = ttk.Frame(path_frame, style="Card.TFrame")
        row1.pack(fill=tk.X, pady=5)
        ttk.Label(row1, text="扫描目录:", style="Card.TLabel", width=12).pack(side=tk.LEFT)
        
        scan_entry = tk.Entry(row1, textvariable=self.scan_dir, 
                             bg=ModernStyle.BG_TERTIARY, fg=ModernStyle.TEXT_PRIMARY,
                             insertbackground=ModernStyle.TEXT_PRIMARY,
                             relief=tk.FLAT, font=("Consolas", 10))
        scan_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        ttk.Button(row1, text="浏览...", style="Secondary.TButton",
                  command=self.select_scan_dir).pack(side=tk.RIGHT)
        
        # Export directory
        row2 = ttk.Frame(path_frame, style="Card.TFrame")
        row2.pack(fill=tk.X, pady=5)
        ttk.Label(row2, text="导出目录:", style="Card.TLabel", width=12).pack(side=tk.LEFT)
        
        export_entry = tk.Entry(row2, textvariable=self.export_dir,
                               bg=ModernStyle.BG_TERTIARY, fg=ModernStyle.TEXT_PRIMARY,
                               insertbackground=ModernStyle.TEXT_PRIMARY,
                               relief=tk.FLAT, font=("Consolas", 10))
        export_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        ttk.Button(row2, text="浏览...", style="Secondary.TButton",
                  command=self.select_export_dir).pack(side=tk.RIGHT)
        
        # Options row
        row3 = ttk.Frame(path_frame, style="Card.TFrame")
        row3.pack(fill=tk.X, pady=(10, 0))
        ttk.Checkbutton(row3, text="递归扫描子目录", variable=self.recursive_scan,
                       style="Dark.TCheckbutton").pack(side=tk.LEFT)
        ttk.Button(row3, text="🔄 刷新Prefab列表", style="Secondary.TButton",
                  command=self.refresh_prefab_list).pack(side=tk.RIGHT)
        
        # Prefab list
        list_frame = ttk.LabelFrame(parent, text="📦 Prefab文件列表", style="Card.TLabelframe", padding=10)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Filter
        filter_frame = ttk.Frame(list_frame, style="Card.TFrame")
        filter_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(filter_frame, text="🔍 筛选:", style="Card.TLabel").pack(side=tk.LEFT)
        self.filter_var = tk.StringVar()
        self.filter_var.trace("w", self.update_prefab_list_filter)
        
        filter_entry = tk.Entry(filter_frame, textvariable=self.filter_var,
                               bg=ModernStyle.BG_TERTIARY, fg=ModernStyle.TEXT_PRIMARY,
                               insertbackground=ModernStyle.TEXT_PRIMARY,
                               relief=tk.FLAT, font=("Consolas", 10))
        filter_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
        
        self.prefab_count_var = tk.StringVar(value="共 0 个文件")
        ttk.Label(filter_frame, textvariable=self.prefab_count_var, 
                 style="Card.TLabel").pack(side=tk.RIGHT)
        
        # Treeview
        tree_frame = ttk.Frame(list_frame, style="Card.TFrame")
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        tree_scroll = ttk.Scrollbar(tree_frame)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.prefab_tree = ttk.Treeview(tree_frame, columns=("selected", "path"), 
                                        show="headings", style="Dark.Treeview",
                                        yscrollcommand=tree_scroll.set)
        self.prefab_tree.heading("selected", text="✓")
        self.prefab_tree.heading("path", text="Prefab 路径")
        self.prefab_tree.column("selected", width=40, anchor="center")
        self.prefab_tree.column("path", width=600)
        self.prefab_tree.pack(fill=tk.BOTH, expand=True)
        tree_scroll.config(command=self.prefab_tree.yview)
        
        self.prefab_tree.bind("<Button-1>", self.on_tree_click)
        
        # Selection buttons
        btn_frame = ttk.Frame(list_frame, style="Card.TFrame")
        btn_frame.pack(fill=tk.X, pady=(10, 0))
        
        ttk.Button(btn_frame, text="全选", style="Secondary.TButton",
                  command=self.select_all_prefabs).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="取消全选", style="Secondary.TButton",
                  command=self.deselect_all_prefabs).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="选择当前筛选项", style="Secondary.TButton",
                  command=self.select_visible_prefabs).pack(side=tk.LEFT, padx=2)
        
        # Action buttons
        action_frame = ttk.Frame(parent, style="Dark.TFrame")
        action_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Button(action_frame, text="🚀 扫描并导出", style="Accent.TButton",
                  command=self.start_scan_thread).pack(side=tk.RIGHT, padx=5)

    def setup_import_tab(self, parent):
        # Import file selection
        import_frame = ttk.LabelFrame(parent, text="📄 导入文件", style="Card.TLabelframe", padding=15)
        import_frame.pack(fill=tk.X, padx=10, pady=10)
        
        row1 = ttk.Frame(import_frame, style="Card.TFrame")
        row1.pack(fill=tk.X, pady=5)
        ttk.Label(row1, text="CSV文件:", style="Card.TLabel", width=12).pack(side=tk.LEFT)
        
        import_entry = tk.Entry(row1, textvariable=self.import_file,
                               bg=ModernStyle.BG_TERTIARY, fg=ModernStyle.TEXT_PRIMARY,
                               insertbackground=ModernStyle.TEXT_PRIMARY,
                               relief=tk.FLAT, font=("Consolas", 10))
        import_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        ttk.Button(row1, text="浏览...", style="Secondary.TButton",
                  command=self.select_import_file).pack(side=tk.RIGHT)
        
        # Options
        options_frame = ttk.LabelFrame(parent, text="⚙️ 选项", style="Card.TLabelframe", padding=15)
        options_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Checkbutton(options_frame, text="自动 P4 Checkout (需要 p4 命令行工具)", 
                       variable=self.p4_enabled, style="Dark.TCheckbutton").pack(anchor=tk.W)
        
        # Info
        info_frame = ttk.LabelFrame(parent, text="📌 说明", style="Card.TLabelframe", padding=15)
        info_frame.pack(fill=tk.X, padx=10, pady=10)
        
        info_text = """此功能将读取CSV文件，并对每个条目执行：
1. 在Prefab中找到对应的Text组件
2. 如果缺少LocComponent则添加
3. 设置StringID并启用LanguageFunc
4. 将新增的Key自动追加到 daydream-entities.csv

• 只有填写了KeyId的行才会被处理
• KeySource为"新增"的Key会导出到entities
• 建议先备份文件再执行"""
        
        ttk.Label(info_frame, text=info_text, style="Card.TLabel", 
                 justify=tk.LEFT).pack(anchor=tk.W)
        
        # Action
        action_frame = ttk.Frame(parent, style="Dark.TFrame")
        action_frame.pack(fill=tk.X, padx=10, pady=20)
        
        ttk.Button(action_frame, text="🔧 应用到Prefab + 导出Entities", style="Accent.TButton",
                  command=self.start_patch_thread).pack(side=tk.RIGHT, padx=5)

    def setup_addkey_tab(self, parent):
        """设置加KEY标签页"""
        # Input file selection
        input_frame = ttk.LabelFrame(parent, text="📄 输入文件", style="Card.TLabelframe", padding=15)
        input_frame.pack(fill=tk.X, padx=10, pady=10)
        
        # 导出的CSV文件（需要添加Key的）
        row1 = ttk.Frame(input_frame, style="Card.TFrame")
        row1.pack(fill=tk.X, pady=5)
        ttk.Label(row1, text="待加KEY的CSV:", style="Card.TLabel", width=15).pack(side=tk.LEFT)
        
        input_entry = tk.Entry(row1, textvariable=self.addkey_input_file,
                              bg=ModernStyle.BG_TERTIARY, fg=ModernStyle.TEXT_PRIMARY,
                              insertbackground=ModernStyle.TEXT_PRIMARY,
                              relief=tk.FLAT, font=("Consolas", 10))
        input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        ttk.Button(row1, text="浏览...", style="Secondary.TButton",
                  command=self.select_addkey_input_file).pack(side=tk.RIGHT)
        
        # 参考的entities文件
        row2 = ttk.Frame(input_frame, style="Card.TFrame")
        row2.pack(fill=tk.X, pady=5)
        ttk.Label(row2, text="参考entities文件:", style="Card.TLabel", width=15).pack(side=tk.LEFT)
        
        ref_entry = tk.Entry(row2, textvariable=self.addkey_ref_file,
                            bg=ModernStyle.BG_TERTIARY, fg=ModernStyle.TEXT_PRIMARY,
                            insertbackground=ModernStyle.TEXT_PRIMARY,
                            relief=tk.FLAT, font=("Consolas", 10))
        ref_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        ttk.Button(row2, text="浏览...", style="Secondary.TButton",
                  command=self.select_addkey_ref_file).pack(side=tk.RIGHT)
        
        # LocIndex文件（用于复用已有Key）
        row_loc = ttk.Frame(input_frame, style="Card.TFrame")
        row_loc.pack(fill=tk.X, pady=5)
        ttk.Label(row_loc, text="LocIndex文件:", style="Card.TLabel", width=15).pack(side=tk.LEFT)
        
        loc_entry = tk.Entry(row_loc, textvariable=self.loc_index_file,
                            bg=ModernStyle.BG_TERTIARY, fg=ModernStyle.TEXT_PRIMARY,
                            insertbackground=ModernStyle.TEXT_PRIMARY,
                            relief=tk.FLAT, font=("Consolas", 10))
        loc_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        ttk.Button(row_loc, text="浏览...", style="Secondary.TButton",
                  command=self.select_loc_index_file).pack(side=tk.RIGHT)
        
        # Key prefix setting
        row3 = ttk.Frame(input_frame, style="Card.TFrame")
        row3.pack(fill=tk.X, pady=5)
        ttk.Label(row3, text="Key前缀:", style="Card.TLabel", width=15).pack(side=tk.LEFT)
        
        prefix_entry = tk.Entry(row3, textvariable=self.key_prefix, width=10,
                               bg=ModernStyle.BG_TERTIARY, fg=ModernStyle.TEXT_PRIMARY,
                               insertbackground=ModernStyle.TEXT_PRIMARY,
                               relief=tk.FLAT, font=("Consolas", 10))
        prefix_entry.pack(side=tk.LEFT)
        
        ttk.Label(row3, text="(例如: T_, UI_, TXT_)", style="Card.TLabel").pack(side=tk.LEFT, padx=10)
        
        # GPT API配置
        gpt_frame = ttk.LabelFrame(parent, text="🤖 GPT翻译配置", style="Card.TLabelframe", padding=15)
        gpt_frame.pack(fill=tk.X, padx=10, pady=10)
        
        # 启用GPT翻译
        row_gpt_enable = ttk.Frame(gpt_frame, style="Card.TFrame")
        row_gpt_enable.pack(fill=tk.X, pady=5)
        ttk.Checkbutton(row_gpt_enable, text="启用GPT翻译 (关闭则使用内置字典翻译)", 
                       variable=self.use_gpt_translation,
                       style="TCheckbutton").pack(side=tk.LEFT)
        
        # API URL
        row_gpt_url = ttk.Frame(gpt_frame, style="Card.TFrame")
        row_gpt_url.pack(fill=tk.X, pady=5)
        ttk.Label(row_gpt_url, text="API URL:", style="Card.TLabel", width=12).pack(side=tk.LEFT)
        
        gpt_url_entry = tk.Entry(row_gpt_url, textvariable=self.gpt_api_url,
                                bg=ModernStyle.BG_TERTIARY, fg=ModernStyle.TEXT_PRIMARY,
                                insertbackground=ModernStyle.TEXT_PRIMARY,
                                relief=tk.FLAT, font=("Consolas", 10))
        gpt_url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        # API Key
        row_gpt_key = ttk.Frame(gpt_frame, style="Card.TFrame")
        row_gpt_key.pack(fill=tk.X, pady=5)
        ttk.Label(row_gpt_key, text="API Key:", style="Card.TLabel", width=12).pack(side=tk.LEFT)
        
        gpt_key_entry = tk.Entry(row_gpt_key, textvariable=self.gpt_api_key,
                                bg=ModernStyle.BG_TERTIARY, fg=ModernStyle.TEXT_PRIMARY,
                                insertbackground=ModernStyle.TEXT_PRIMARY,
                                relief=tk.FLAT, font=("Consolas", 10), show="*")
        gpt_key_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        # Model
        row_gpt_model = ttk.Frame(gpt_frame, style="Card.TFrame")
        row_gpt_model.pack(fill=tk.X, pady=5)
        ttk.Label(row_gpt_model, text="Model:", style="Card.TLabel", width=12).pack(side=tk.LEFT)
        
        gpt_model_entry = tk.Entry(row_gpt_model, textvariable=self.gpt_model, width=20,
                                  bg=ModernStyle.BG_TERTIARY, fg=ModernStyle.TEXT_PRIMARY,
                                  insertbackground=ModernStyle.TEXT_PRIMARY,
                                  relief=tk.FLAT, font=("Consolas", 10))
        gpt_model_entry.pack(side=tk.LEFT)
        
        ttk.Label(row_gpt_model, text="(如: gpt-3.5-turbo, gpt-4)", 
                 style="Card.TLabel").pack(side=tk.LEFT, padx=10)
        
        # Info
        info_frame = ttk.LabelFrame(parent, text="📌 说明", style="Card.TLabelframe", padding=15)
        info_frame.pack(fill=tk.X, padx=10, pady=10)
        
        info_text = """功能说明：
1. 生成Key: 读取CSV，为每个text分配KeyId
   • 如果英文内容在LocIndex中已存在 → 复用已有Key
   • 如果不存在 → 生成新Key
2. GPT翻译: 自动使用GPT API进行中英互译

注意: LocIndex默认使用当前目录下的LocIndex.csv"""
        
        ttk.Label(info_frame, text=info_text, style="Card.TLabel", 
                 justify=tk.LEFT).pack(anchor=tk.W)
        
        # Action buttons
        action_frame = ttk.Frame(parent, style="Dark.TFrame")
        action_frame.pack(fill=tk.X, padx=10, pady=20)
        
        ttk.Button(action_frame, text="🔑 生成Key并导出", style="Accent.TButton",
                  command=self.start_addkey_thread).pack(side=tk.RIGHT, padx=5)

    def show_cookie_help(self):
        """显示如何获取Cookie的帮助"""
        help_text = """如何获取Transify Cookie:

1. 在浏览器中打开 https://transify.garena.com 并登录

2. 按 F12 打开开发者工具

3. 切换到 "Network" (网络) 标签页

4. 刷新页面或进行任意操作

5. 点击任意一个请求，在右侧找到 "Request Headers"

6. 复制 "Cookie:" 后面的完整内容

7. 粘贴到上面的Cookie输入框中

注意: Cookie可能会过期，如果上传失败请重新获取"""
        
        messagebox.showinfo("如何获取Cookie", help_text)

    def select_addkey_input_file(self):
        path = filedialog.askopenfilename(
            initialdir=self.export_dir.get() or os.getcwd(),
            title="选择待加KEY的CSV文件",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")]
        )
        if path:
            self.addkey_input_file.set(os.path.normpath(path))

    def select_addkey_ref_file(self):
        path = filedialog.askopenfilename(
            initialdir=os.getcwd(),
            title="选择参考的entities文件",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")]
        )
        if path:
            self.addkey_ref_file.set(os.path.normpath(path))
            # 自动加载已存在的Key
            self.load_existing_keys()

    def load_existing_keys(self):
        """加载参考文件中已存在的Key"""
        ref_file = self.addkey_ref_file.get()
        if not ref_file or not os.path.exists(ref_file):
            return
        
        self.existing_keys.clear()
        try:
            with open(ref_file, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    key = (row.get("Key") or "").strip()
                    if key:
                        self.existing_keys.add(key)
            self.log(f"已加载 {len(self.existing_keys)} 个已存在的Key")
        except Exception as e:
            self.log(f"加载参考文件失败: {e}")

    def select_loc_index_file(self):
        """选择LocIndex文件（用于复用已有Key）"""
        path = filedialog.askopenfilename(
            initialdir=os.getcwd(),
            title="选择LocIndex文件",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")]
        )
        if path:
            self.loc_index_file.set(os.path.normpath(path))
            # 自动加载LocIndex映射
            self.load_loc_index()

    def load_loc_index(self):
        """加载LocIndex文件，建立英文内容->Key的映射"""
        loc_file = self.loc_index_file.get()
        if not loc_file or not os.path.exists(loc_file):
            return
        
        self.loc_index_map.clear()
        try:
            with open(loc_file, 'r', encoding='utf-8-sig') as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) >= 2:
                        key = row[0].strip()
                        content = row[1].strip()
                        if key and content:
                            # 英文内容 -> Key 的映射（用于复用）
                            self.loc_index_map[content] = key
            self.log(f"已加载LocIndex: {len(self.loc_index_map)} 个Key-Content映射")
        except Exception as e:
            self.log(f"加载LocIndex失败: {e}")

    # 中英文翻译词典（双向）
    TRANSLATION_DICT = {
        # 按钮/操作
        '确定': 'Confirm', '取消': 'Cancel', '返回': 'Back', '关闭': 'Close',
        '开始': 'Start', '结束': 'End', '提交': 'Submit', '保存': 'Save',
        '删除': 'Delete', '编辑': 'Edit', '添加': 'Add', '创建': 'Create',
        '设置': 'Settings', '帮助': 'Help', '提示': 'Tip', '警告': 'Warning',
        '错误': 'Error', '成功': 'Success', '失败': 'Failed', '加载': 'Loading',
        '加载中': 'Loading...', '请稍候': 'Please wait', '请等待': 'Please wait',
        '确认': 'Confirm', '继续': 'Continue', '重试': 'Retry', '跳过': 'Skip',
        '下一步': 'Next', '上一步': 'Previous', '完成': 'Done', '领取': 'Claim',
        '刷新': 'Refresh', '搜索': 'Search', '筛选': 'Filter', '排序': 'Sort',
        '复制': 'Copy', '粘贴': 'Paste', '撤销': 'Undo', '重做': 'Redo',
        '分享': 'Share', '收藏': 'Favorite', '点赞': 'Like', '评论': 'Comment',
        '发送': 'Send', '接收': 'Receive', '上传': 'Upload', '下载': 'Download',
        '播放': 'Play', '暂停': 'Pause', '停止': 'Stop', '重播': 'Replay',
        # 游戏相关
        '购买': 'Buy', '出售': 'Sell', '升级': 'Upgrade', '解锁': 'Unlock',
        '等级': 'Level', '经验': 'EXP', '金币': 'Gold', '钻石': 'Diamond',
        '攻击': 'Attack', '防御': 'Defense', '生命': 'HP', '魔法': 'MP',
        '技能': 'Skill', '装备': 'Equipment', '背包': 'Bag', '商店': 'Shop',
        '任务': 'Quest', '成就': 'Achievement', '排行': 'Ranking', '好友': 'Friends',
        '聊天': 'Chat', '邮件': 'Mail', '公告': 'Announcement', '活动': 'Event',
        '奖励': 'Reward', '免费': 'Free', '限时': 'Limited Time', '新': 'New',
        '热门': 'Hot', '推荐': 'Recommended', '更多': 'More', '全部': 'All',
        '角色': 'Character', '英雄': 'Hero', '怪物': 'Monster', 'Boss': 'Boss',
        '战斗': 'Battle', '副本': 'Dungeon', '关卡': 'Stage', '挑战': 'Challenge',
        '胜利': 'Victory', '失败': 'Defeat', '平局': 'Draw', '结算': 'Settlement',
        '体力': 'Stamina', '能量': 'Energy', '积分': 'Points', '代币': 'Token',
        # 账号相关
        '登录': 'Login', '注册': 'Register', '退出': 'Logout', '账号': 'Account',
        '密码': 'Password', '用户名': 'Username', '昵称': 'Nickname',
        '头像': 'Avatar', '个人资料': 'Profile', '修改密码': 'Change Password',
        '忘记密码': 'Forgot Password', '找回密码': 'Reset Password',
        '绑定': 'Bind', '解绑': 'Unbind', '验证': 'Verify', '验证码': 'Verification Code',
        # 提示文本
        '请输入': 'Please enter', '请选择': 'Please select', '请确认': 'Please confirm',
        '是否确定': 'Are you sure', '确定要': 'Are you sure to',
        '操作成功': 'Operation successful', '操作失败': 'Operation failed',
        '网络错误': 'Network error', '连接失败': 'Connection failed',
        '加载失败': 'Loading failed', '保存成功': 'Saved successfully',
        '删除成功': 'Deleted successfully', '提交成功': 'Submitted successfully',
        '数据为空': 'No data', '暂无数据': 'No data available',
        '敬请期待': 'Coming soon', '即将开放': 'Coming soon',
        '已拥有': 'Already owned', '未解锁': 'Not unlocked', '已解锁': 'Unlocked',
        '不足': 'Insufficient', '已满': 'Full', '已过期': 'Expired',
        '今日': 'Today', '昨日': 'Yesterday', '本周': 'This week', '本月': 'This month',
        # 数量/时间
        '天': 'Day', '小时': 'Hour', '分钟': 'Minute', '秒': 'Second',
        '次': 'Time(s)', '个': '', '件': '', '张': '',
    }

    def translate_text(self, text, to_chinese=False):
        """中英互译 - 支持GPT API或内置字典"""
        if not text:
            return ""
        
        # 检测是否包含中文
        has_chinese = bool(re.search(r'[\u4e00-\u9fff]', text))
        
        # 如果语言匹配目标，直接返回
        if to_chinese and has_chinese:
            return text
        if not to_chinese and not has_chinese:
            return text
        
        # 检查缓存
        cache_key = f"{text}_{to_chinese}"
        if cache_key in self.translation_cache:
            return self.translation_cache[cache_key]
        
        # 使用GPT翻译
        if self.use_gpt_translation.get() and self.gpt_api_key.get():
            result = self.translate_with_gpt(text, to_chinese)
            if result:
                self.translation_cache[cache_key] = result
                return result
            # GPT失败时回退到字典翻译
        
        # 使用内置字典翻译
        result = self.translate_with_dict(text, to_chinese)
        self.translation_cache[cache_key] = result
        return result

    def translate_with_gpt(self, text, to_chinese=False):
        """使用GPT API进行翻译"""
        if not HAS_REQUESTS:
            self.log("⚠️ 需要安装requests库才能使用GPT翻译")
            return ""
        
        api_url = self.gpt_api_url.get().rstrip('/')
        api_key = self.gpt_api_key.get()
        model = self.gpt_model.get()
        
        # 自动补全URL路径
        if not api_url.endswith('/chat/completions'):
            if api_url.endswith('/v1'):
                api_url = api_url + '/chat/completions'
            else:
                api_url = api_url + '/v1/chat/completions'
        
        if not api_key:
            return ""
        
        try:
            if to_chinese:
                prompt = f"请将以下英文翻译成简体中文，只返回翻译结果，不要添加任何解释或标点符号变化：\n\n{text}"
            else:
                prompt = f"请将以下中文翻译成英文，只返回翻译结果，不要添加任何解释或标点符号变化：\n\n{text}"
            
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            
            data = {
                "model": model,
                "messages": [
                    {"role": "system", "content": "你是一个专业的游戏本地化翻译专家。翻译要求：1. 保持游戏术语的专业性 2. 翻译简洁准确 3. 只输出翻译结果，不要任何解释"},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3,
                "max_tokens": 500
            }
            
            response = requests.post(api_url, headers=headers, json=data, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                translated = result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                if translated:
                    return translated
            else:
                self.log(f"⚠️ GPT API错误: HTTP {response.status_code}")
                
        except requests.exceptions.Timeout:
            self.log("⚠️ GPT API超时")
        except Exception as e:
            self.log(f"⚠️ GPT翻译失败: {e}")
        
        return ""

    def translate_with_dict(self, text, to_chinese=False):
        """使用内置字典进行翻译"""
        # 检测是否包含中文
        has_chinese = bool(re.search(r'[\u4e00-\u9fff]', text))
        
        if to_chinese and not has_chinese:
            # 英文转中文：反向查找
            result = text
            for cn, en in self.TRANSLATION_DICT.items():
                if en.lower() in text.lower():
                    # 简单替换（大小写不敏感）
                    pattern = re.compile(re.escape(en), re.IGNORECASE)
                    result = pattern.sub(cn, result)
            return result if result != text else ""  # 如果没有翻译则返回空
        elif not to_chinese and has_chinese:
            # 中文转英文：正向查找
            result = text
            for cn, en in self.TRANSLATION_DICT.items():
                if cn in text:
                    result = result.replace(cn, en)
            # 如果还有中文残留，说明翻译不完整
            if re.search(r'[\u4e00-\u9fff]', result):
                return ""  # 返回空表示需要人工翻译
            return result
        
        return text  # 语言匹配，直接返回

    def generate_key_from_text(self, text, used_keys):
        """根据文本内容生成Key"""
        if not text:
            return None
        
        prefix = self.key_prefix.get() or "T_"
        
        # 清理文本
        clean_text = text.strip()
        
        # 移除HTML标签
        clean_text = re.sub(r'<[^>]+>', '', clean_text)
        
        # 移除特殊字符，保留字母、数字、中文、空格
        clean_text = re.sub(r'[^\w\s\u4e00-\u9fff]', ' ', clean_text)
        
        # 检测是否包含中文
        has_chinese = bool(re.search(r'[\u4e00-\u9fff]', clean_text))
        
        if has_chinese:
            # 中文处理：尝试匹配关键词
            matched_key = None
            for cn, en in self.TRANSLATION_DICT.items():
                if cn in clean_text:
                    matched_key = en
                    break
            
            if matched_key:
                key_base = matched_key.replace(' ', '_')
            else:
                # 无法匹配时使用序号
                key_base = f"Text_{len(used_keys) + 1}"
        else:
            # 英文处理：提取关键词
            words = clean_text.split()
            # 过滤掉太短的词和常见词
            stop_words = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 
                         'to', 'of', 'and', 'or', 'in', 'on', 'at', 'for', 'with',
                         'it', 'this', 'that', 'you', 'we', 'they', 'i', 'he', 'she'}
            
            key_words = []
            for word in words:
                word_clean = word.strip().capitalize()
                if len(word_clean) > 1 and word_clean.lower() not in stop_words:
                    key_words.append(word_clean)
                    if len(key_words) >= 3:
                        break
            
            if key_words:
                key_base = '_'.join(key_words)
            else:
                key_base = f"Text_{len(used_keys) + 1}"
        
        # 清理key_base中的非法字符
        key_base = re.sub(r'[^\w]', '_', key_base)
        key_base = re.sub(r'_+', '_', key_base)  # 合并多个下划线
        key_base = key_base.strip('_')
        
        # 构建完整Key并转为大写
        full_key = f"{prefix}{key_base}".upper()
        
        # 确保唯一性
        if full_key in self.existing_keys or full_key in used_keys:
            counter = 1
            while f"{full_key}_{counter}" in self.existing_keys or f"{full_key}_{counter}" in used_keys:
                counter += 1
            full_key = f"{full_key}_{counter}"
        
        return full_key

    def start_addkey_thread(self):
        input_file = self.addkey_input_file.get()
        ref_file = self.addkey_ref_file.get()
        
        if not input_file:
            messagebox.showerror("错误", "请先选择待加KEY的CSV文件")
            return
        
        if not os.path.exists(input_file):
            messagebox.showerror("错误", f"文件不存在:\n{input_file}")
            return
        
        if ref_file and not os.path.exists(ref_file):
            messagebox.showerror("错误", f"参考文件不存在:\n{ref_file}")
            return
        
        threading.Thread(target=self.run_addkey, daemon=True).start()

    def run_addkey(self):
        try:
            input_file = self.addkey_input_file.get()
            ref_file = self.addkey_ref_file.get()
            loc_file = self.loc_index_file.get()
            export_dir = self.export_dir.get() or os.path.dirname(input_file)
            
            self.log("=" * 40)
            self.log("开始加KEY处理...")
            self.update_status("处理中...")
            
            # 清空翻译缓存
            self.translation_cache.clear()
            
            # 显示翻译配置
            if self.use_gpt_translation.get() and self.gpt_api_key.get():
                self.log(f"🤖 GPT翻译: 已启用")
                self.log(f"   API: {self.gpt_api_url.get()[:50]}...")
                self.log(f"   Model: {self.gpt_model.get()}")
            else:
                self.log("📖 使用内置字典翻译")
            
            # 加载参考文件中的已存在Key（用于避免Key重复）
            if ref_file and os.path.exists(ref_file):
                self.load_existing_keys()
            
            # 加载LocIndex文件（用于复用已有Key）
            if loc_file and os.path.exists(loc_file):
                self.load_loc_index()
                self.log(f"LocIndex: 已加载 {len(self.loc_index_map)} 个Key-Content映射")
            else:
                self.log("⚠️ 未指定LocIndex文件，将全部生成新Key")
            
            # 读取输入文件
            self.log(f"读取文件: {os.path.basename(input_file)}")
            rows = []
            with open(input_file, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                original_fieldnames = list(reader.fieldnames)
                rows = list(reader)
            
            self.log(f"共 {len(rows)} 行数据")
            
            # 添加新列：KeySource（标记Key来源：复用/新增）
            if "KeySource" not in original_fieldnames:
                fieldnames = original_fieldnames + ["KeySource"]
            else:
                fieldnames = original_fieldnames
            
            # 处理每一行
            new_keys = []  # 新增的Key记录
            used_keys = set()  # 本次已使用的Key
            new_count = 0      # 新增Key数量
            reused_count = 0   # 复用Key数量
            
            self.update_progress(0, len(rows))
            
            skipped_count = 0  # prefab already has key
            
            for i, row in enumerate(rows):
                original_text = (row.get("Original Text") or "").strip()
                
                if not original_text:
                    row["KeySource"] = ""
                    continue
                
                existing_key_from_prefab = (row.get("KeyId") or "").strip()
                if existing_key_from_prefab:
                    row["KeySource"] = "prefab已有"
                    used_keys.add(existing_key_from_prefab)
                    skipped_count += 1
                    self.log(f"  [skip] prefab已有Key: {existing_key_from_prefab}")
                    continue
                
                # 获取英文内容（用于查找已有Key）
                has_chinese = bool(re.search(r'[\u4e00-\u9fff]', original_text))
                if has_chinese:
                    # 原文是中文，翻译成英文
                    chinese_text = original_text
                    english_text = self.translate_text(original_text, to_chinese=False)
                    if english_text and english_text != original_text:
                        self.log(f"  🔄 翻译: {original_text[:20]}... → {english_text[:30]}...")
                else:
                    # 原文是英文，翻译成中文
                    english_text = original_text
                    chinese_text = self.translate_text(original_text, to_chinese=True)
                    if chinese_text and chinese_text != original_text:
                        self.log(f"  🔄 翻译: {original_text[:30]}... → {chinese_text[:20]}...")
                
                # 检查英文内容是否在LocIndex中已存在
                found_key = None
                if english_text in self.loc_index_map:
                    found_key = self.loc_index_map[english_text]
                
                if found_key:
                    # 复用已有Key
                    row["KeyId"] = found_key
                    row["KeySource"] = "复用"
                    used_keys.add(found_key)
                    reused_count += 1
                    self.log(f"  ♻️ 复用Key: {found_key} (匹配: {english_text[:30]}...)" if len(english_text) > 30 else f"  ♻️ 复用Key: {found_key} (匹配: {english_text})")
                else:
                    # 生成新Key
                    new_key = self.generate_key_from_text(original_text, used_keys)
                    if new_key:
                        row["KeyId"] = new_key
                        row["KeySource"] = "新增"
                        used_keys.add(new_key)
                        new_count += 1
                        
                        # 记录新增的Key (格式: Key, Content, Word Count, Context, Original)
                        new_keys.append({
                            "Key": new_key,
                            "Content": english_text,  # 英文
                            "Word Count": len(original_text),
                            "Context": row.get("Prefab Path", ""),
                            "Original": chinese_text  # 中文
                        })
                        
                        self.log(f"  ✨ 新增Key: {new_key}")
                
                if (i + 1) % 10 == 0:
                    self.update_progress(i + 1)
                    self.update_status(f"处理中... {i + 1}/{len(rows)}")
            
            self.update_progress(len(rows))
            
            self.log("-" * 40)
            self.log(f"处理完成:")
            self.log(f"  [skip] prefab已有Key: {skipped_count} 个")
            self.log(f"  ♻️ 复用已有Key: {reused_count} 个")
            self.log(f"  ✨ 新增Key: {new_count} 个")
            self.log(f"  📊 共处理: {skipped_count + reused_count + new_count} 个text")
            
            # 导出更新后的CSV
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # 1. 更新后的原CSV（包含KeySource列）
            updated_file = os.path.join(export_dir, f"PrefabExport_WithKeys_{timestamp}.csv")
            with open(updated_file, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            self.log(f"✅ 已保存更新后的CSV: {os.path.basename(updated_file)}")
            
            # 2. 新增Key的entities表 (放在单独的NewKeys文件夹)
            entities_file = None
            if new_keys:
                # 创建NewKeys子文件夹
                newkeys_dir = os.path.join(export_dir, "NewKeys")
                if not os.path.exists(newkeys_dir):
                    os.makedirs(newkeys_dir)
                
                entities_file = os.path.join(newkeys_dir, f"NewKeys_Entities_{timestamp}.csv")
                # 使用简化的格式: Key, Content, Word Count, Context, Original
                entities_fieldnames = ["Key", "Content", "Word Count", "Context", "Original"]
                with open(entities_file, 'w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.DictWriter(f, fieldnames=entities_fieldnames)
                    writer.writeheader()
                    writer.writerows(new_keys)
                self.log(f"✅ 已保存新增Key表: NewKeys/{os.path.basename(entities_file)}")
                self.log(f"   共 {len(new_keys)} 个新Key")
                
                # 保存路径供上传使用
                self.last_exported_entities_file = entities_file
            else:
                self.log("ℹ️ 没有新增Key需要导出（全部复用已有Key）")
                self.last_exported_entities_file = None
            
            self.update_progress(0)
            self.update_status("就绪")
            
            msg = f"加KEY处理完成!\n\nprefab已有Key: {skipped_count} 个\n新增Key: {new_count} 个\n复用已有Key: {reused_count} 个\n\n"
            msg += f"更新后的CSV:\n{updated_file}\n\n"
            if entities_file:
                msg += f"新增Key表:\n{entities_file}"
            
            self.root.after(0, lambda: messagebox.showinfo("完成", msg))
            return entities_file  # 返回entities文件路径供上传使用
            
        except Exception as e:
            self.log(f"❌ 处理出错: {e}")
            import traceback
            self.log(traceback.format_exc())
            self.update_status("出错")
            self.root.after(0, lambda: messagebox.showerror("错误", f"处理失败: {e}"))
            return None

    # --- Transify Upload ---
    def start_upload_transify_thread(self):
        """上传到Transify（使用上次导出的文件）"""
        if not self.last_exported_entities_file:
            # 尝试选择文件
            path = filedialog.askopenfilename(
                initialdir=os.path.join(self.export_dir.get() or os.getcwd(), "NewKeys"),
                title="选择要上传的entities CSV文件",
                filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")]
            )
            if path:
                self.last_exported_entities_file = path
            else:
                messagebox.showerror("错误", "请先生成Key或选择要上传的entities文件")
                return
        
        if not self.transify_cookie.get():
            messagebox.showerror("错误", "请先配置Transify Cookie")
            return
        
        threading.Thread(target=self.upload_to_transify, daemon=True).start()

    def start_addkey_and_upload_thread(self):
        """生成Key并上传到Transify"""
        if not self.transify_cookie.get():
            messagebox.showerror("错误", "请先配置Transify Cookie")
            return
        
        threading.Thread(target=self.run_addkey_and_upload, daemon=True).start()

    def run_addkey_and_upload(self):
        """生成Key并上传"""
        # 先生成Key
        entities_file = self.run_addkey()
        
        # 如果生成成功，自动上传
        if entities_file and os.path.exists(entities_file):
            self.log("-" * 40)
            self.log("开始上传到Transify...")
            self.upload_to_transify()

    def upload_to_transify(self):
        """上传CSV到Transify"""
        try:
            if not HAS_REQUESTS:
                self.log("❌ 需要安装requests库: pip install requests")
                self.root.after(0, lambda: messagebox.showerror("错误", "需要安装requests库\n运行: pip install requests"))
                return
            
            file_path = self.last_exported_entities_file
            if not file_path or not os.path.exists(file_path):
                self.log("❌ 找不到要上传的文件")
                return
            
            self.log("=" * 40)
            self.log("上传到Transify...")
            self.log(f"文件: {os.path.basename(file_path)}")
            self.update_status("上传中...")
            
            base_url = self.transify_url.get().rstrip('/')
            resource_id = self.transify_resource_id.get()
            cookie = self.transify_cookie.get()
            
            if not resource_id:
                self.log("❌ 请配置资源ID")
                return
            
            if not cookie:
                self.log("❌ 请配置Cookie")
                return
            
            # 上传URL
            upload_url = f"{base_url}/api/resources/{resource_id}/entities/import"
            
            self.log(f"上传地址: {upload_url}")
            
            # 准备文件
            with open(file_path, 'rb') as f:
                files = {
                    'file': (os.path.basename(file_path), f, 'text/csv')
                }
                
                headers = {
                    'Cookie': cookie,
                    'Accept': 'application/json',
                    'Origin': base_url,
                    'Referer': f'{base_url}/resources/{resource_id}'
                }
                
                # 发送请求
                self.log("发送请求...")
                response = requests.post(upload_url, files=files, headers=headers, timeout=60)
            
            self.log(f"响应状态: {response.status_code}")
            
            if response.status_code == 200:
                try:
                    result = response.json()
                    self.log(f"响应内容: {json.dumps(result, ensure_ascii=False, indent=2)}")
                    
                    if result.get('success') or result.get('code') == 0:
                        self.log("✅ 上传成功!")
                        self.root.after(0, lambda: messagebox.showinfo("成功", "上传到Transify成功!"))
                    else:
                        error_msg = result.get('message') or result.get('msg') or str(result)
                        self.log(f"⚠️ 上传响应: {error_msg}")
                        self.root.after(0, lambda: messagebox.showwarning("提示", f"上传响应:\n{error_msg}"))
                except:
                    self.log(f"响应内容: {response.text[:500]}")
                    self.log("✅ 上传完成（请检查Transify确认结果）")
                    self.root.after(0, lambda: messagebox.showinfo("完成", "上传请求已发送\n请在Transify网站确认结果"))
            
            elif response.status_code == 401 or response.status_code == 403:
                self.log("❌ 认证失败，请检查Cookie是否正确或已过期")
                self.root.after(0, lambda: messagebox.showerror("错误", "认证失败\n请重新获取Cookie"))
            
            elif response.status_code == 404:
                self.log("❌ 资源不存在，请检查资源ID是否正确")
                self.root.after(0, lambda: messagebox.showerror("错误", f"资源ID {resource_id} 不存在\n请检查配置"))
            
            else:
                self.log(f"❌ 上传失败: HTTP {response.status_code}")
                self.log(f"响应: {response.text[:500]}")
                self.root.after(0, lambda: messagebox.showerror("错误", f"上传失败: HTTP {response.status_code}"))
            
            self.update_status("就绪")
            self.save_config()  # 保存配置
            
        except requests.exceptions.Timeout:
            self.log("❌ 请求超时")
            self.root.after(0, lambda: messagebox.showerror("错误", "请求超时，请检查网络连接"))
            self.update_status("超时")
        except requests.exceptions.ConnectionError as e:
            self.log(f"❌ 连接失败: {e}")
            self.root.after(0, lambda: messagebox.showerror("错误", "连接失败，请检查网络"))
            self.update_status("连接失败")
        except Exception as e:
            self.log(f"❌ 上传出错: {e}")
            import traceback
            self.log(traceback.format_exc())
            self.update_status("出错")
            self.root.after(0, lambda: messagebox.showerror("错误", f"上传失败: {e}"))

    def setup_settings_tab(self, parent):
        # Localization settings
        loc_frame = ttk.LabelFrame(parent, text="🌐 本地化组件配置", style="Card.TLabelframe", padding=15)
        loc_frame.pack(fill=tk.X, padx=10, pady=10)
        
        row1 = ttk.Frame(loc_frame, style="Card.TFrame")
        row1.pack(fill=tk.X, pady=5)
        ttk.Label(row1, text="LocComponent GUID:", style="Card.TLabel").pack(side=tk.LEFT)
        
        guid_entry = tk.Entry(row1, textvariable=self.loc_guid,
                             bg=ModernStyle.BG_TERTIARY, fg=ModernStyle.TEXT_PRIMARY,
                             insertbackground=ModernStyle.TEXT_PRIMARY,
                             relief=tk.FLAT, font=("Consolas", 10), width=40)
        guid_entry.pack(side=tk.LEFT, padx=10)
        
        ttk.Button(row1, text="重置默认", style="Secondary.TButton",
                  command=lambda: self.loc_guid.set(DEFAULT_LOC_GUID)).pack(side=tk.LEFT)
        
        ttk.Label(loc_frame, text="提示: 这是你的LocComponent脚本的GUID，可在.meta文件中找到",
                 style="Card.TLabel").pack(anchor=tk.W, pady=(10, 0))
        
        # About
        about_frame = ttk.LabelFrame(parent, text="ℹ️ 关于", style="Card.TLabelframe", padding=15)
        about_frame.pack(fill=tk.X, padx=10, pady=10)
        
        about_text = """Unity Prefab Text Extractor - 通用版本

功能:
• 扫描Unity Prefab文件中的所有Text/TMP文本组件
• 导出文本内容到CSV以便翻译
• 将翻译后的KeyId写回Prefab

支持:
• Unity Text (Legacy)
• TextMeshPro (TMP)
• 自定义LocComponent配置"""
        
        ttk.Label(about_frame, text=about_text, style="Card.TLabel",
                 justify=tk.LEFT).pack(anchor=tk.W)

    # --- Directory Selection ---
    def select_scan_dir(self):
        path = filedialog.askdirectory(initialdir=self.scan_dir.get() or os.getcwd(),
                                       title="选择要扫描的Unity项目文件夹")
        if path:
            self.scan_dir.set(os.path.normpath(path))
            self.save_config()
            self.refresh_prefab_list()

    def select_export_dir(self):
        path = filedialog.askdirectory(initialdir=self.export_dir.get() or os.getcwd(),
                                       title="选择导出目录")
        if path:
            self.export_dir.set(os.path.normpath(path))
            self.save_config()

    def select_import_file(self):
        path = filedialog.askopenfilename(
            initialdir=self.export_dir.get() or os.getcwd(),
            title="选择CSV文件",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")]
        )
        if path:
            self.import_file.set(os.path.normpath(path))

    # --- Prefab List Management ---
    def refresh_prefab_list(self):
        scan_path = self.scan_dir.get()
        if not scan_path or not os.path.exists(scan_path):
            self.log("请先选择有效的扫描目录")
            return
        
        self.all_prefabs = []
        self.log(f"正在扫描 {scan_path} ...")
        self.status_var.set("扫描中...")
        
        if self.recursive_scan.get():
            for root, _, files in os.walk(scan_path):
                for file in files:
                    if file.lower().endswith(".prefab"):
                        rel_path = os.path.relpath(os.path.join(root, file), scan_path)
                        self.all_prefabs.append(rel_path)
        else:
            for file in os.listdir(scan_path):
                if file.lower().endswith(".prefab"):
                    self.all_prefabs.append(file)
        
        self.all_prefabs.sort()
        self.update_prefab_list_filter()
        self.log(f"找到 {len(self.all_prefabs)} 个Prefab文件")
        self.status_var.set(f"就绪 - 找到 {len(self.all_prefabs)} 个文件")

    def update_prefab_list_filter(self, *args):
        search = self.filter_var.get().lower()
        self.prefab_tree.delete(*self.prefab_tree.get_children())
        self.prefab_map = {}
        
        visible_count = 0
        for path in self.all_prefabs:
            if search in path.lower():
                check = "✓" if path in self.selected_prefabs else ""
                item_id = self.prefab_tree.insert("", "end", values=(check, path))
                self.prefab_map[item_id] = path
                visible_count += 1
        
        self.prefab_count_var.set(f"显示 {visible_count} / 共 {len(self.all_prefabs)} 个文件")

    def on_tree_click(self, event):
        region = self.prefab_tree.identify_region(event.x, event.y)
        if region == "heading":
            return
        
        item_id = self.prefab_tree.identify_row(event.y)
        if item_id:
            path = self.prefab_map.get(item_id)
            if path:
                if path in self.selected_prefabs:
                    self.selected_prefabs.remove(path)
                    self.prefab_tree.item(item_id, values=("", path))
                else:
                    self.selected_prefabs.add(path)
                    self.prefab_tree.item(item_id, values=("✓", path))

    def select_all_prefabs(self):
        self.selected_prefabs = set(self.all_prefabs)
        self.update_prefab_list_filter()

    def deselect_all_prefabs(self):
        self.selected_prefabs.clear()
        self.update_prefab_list_filter()
        
    def select_visible_prefabs(self):
        for item_id in self.prefab_tree.get_children():
            path = self.prefab_map.get(item_id)
            if path:
                self.selected_prefabs.add(path)
        self.update_prefab_list_filter()

    # --- Logging (Thread-safe) ---
    def log(self, message):
        """Thread-safe logging"""
        def _log():
            timestamp = datetime.now().strftime('%H:%M:%S')
            self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
            self.log_text.see(tk.END)
        self.root.after(0, _log)
    
    def update_progress(self, value, maximum=None):
        """Thread-safe progress update"""
        def _update():
            if maximum is not None:
                self.progress["maximum"] = maximum
            self.progress["value"] = value
        self.root.after(0, _update)
    
    def update_status(self, text):
        """Thread-safe status update"""
        self.root.after(0, lambda: self.status_var.set(text))

    # --- P4 Integration ---
    def p4_checkout(self, file_path):
        if not self.p4_enabled.get():
            return
        if not os.path.exists(file_path):
            return
        
        dir_name = os.path.dirname(file_path)
        base_name = os.path.basename(file_path)
        
        try:
            cmd = f'p4 edit "{base_name}"'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=dir_name)
            
            if result.returncode == 0:
                if "opened for edit" in result.stdout or "currently opened" in result.stdout:
                    self.log(f"  [P4] 已签出: {base_name}")
                else:
                    self.log(f"  [P4] {result.stdout.strip()}")
            else:
                self.log(f"  [P4] 错误: {result.stderr.strip()}")
        except Exception as e:
            self.log(f"  [P4] 异常: {e}")

    # --- Scan & Export ---
    def start_scan_thread(self):
        self.save_config()
        
        scan_path = self.scan_dir.get()
        export_path = self.export_dir.get()
        
        # 验证路径
        if not scan_path:
            messagebox.showerror("错误", "请先设置扫描目录!")
            return
        
        if not os.path.exists(scan_path):
            messagebox.showerror("错误", f"扫描目录不存在:\n{scan_path}")
            return
        
        if not export_path:
            messagebox.showerror("错误", "请先设置导出目录!")
            return
        
        if not self.selected_prefabs:
            if not self.all_prefabs:
                messagebox.showerror("错误", "未找到任何Prefab文件!\n请先点击'刷新Prefab列表'")
                return
            if not messagebox.askyesno("确认", "未选择任何Prefab文件。\n是否扫描所有找到的Prefab?"):
                return
            self.selected_prefabs = set(self.all_prefabs)
        
        self.log("=" * 40)
        self.log("开始扫描任务...")
        threading.Thread(target=self.run_scan, daemon=True).start()

    def run_scan(self):
        try:
            scan_path = self.scan_dir.get()
            export_path = self.export_dir.get()
            
            self.log(f"扫描目录: {scan_path}")
            self.log(f"导出目录: {export_path}")
            
            # Ensure export dir exists
            if not os.path.exists(export_path):
                os.makedirs(export_path)
                self.log(f"创建导出目录: {export_path}")
            
            prefabs = [os.path.join(scan_path, p) for p in self.selected_prefabs]
            total_count = len(prefabs)
            
            self.log(f"待扫描文件数: {total_count}")
            self.update_progress(0, total_count)
            self.update_status(f"扫描中... 0/{total_count}")
            
            results = []
            loc_guid = self.loc_guid.get()
            text_found_count = 0
            
            for i, prefab_path in enumerate(prefabs):
                file_name = os.path.basename(prefab_path)
                
                try:
                    if not os.path.exists(prefab_path):
                        self.log(f"  ⚠️ 文件不存在: {file_name}")
                        continue
                    
                    parser = UnityYAMLParser(prefab_path)
                    parser.parse()
                    
                    file_text_count = 0
                    
                    for file_id, obj in parser.objects.items():
                        if obj['class_id'] == 114:  # MonoBehaviour
                            text_val = None
                            raw_content = "".join(obj['lines_raw'])
                            
                            # Find text property (TMP: m_text, Legacy: m_Text)
                            m_text_match = re.search(r'm_text: (.*)', raw_content, re.IGNORECASE)
                            if not m_text_match:
                                m_text_match = re.search(r'm_Text: (.*)', raw_content)
                            
                            if m_text_match:
                                text_val = m_text_match.group(1).strip()
                                
                                if text_val.startswith('"') and text_val.endswith('"'):
                                    text_val = text_val[1:-1]
                                    try:
                                        text_val = text_val.encode('utf-8').decode('unicode_escape')
                                    except Exception:
                                        pass
                                
                                if not text_val:
                                    continue
                                
                                if re.match(r'^[\d\s.,\-+%/:\\]+$', text_val):
                                    continue

                                # Find GameObject
                                go_match = re.search(r'm_GameObject: {fileID: (\d+)}', raw_content)
                                if go_match:
                                    go_id = go_match.group(1)
                                    
                                    # Check for existing LocComponent
                                    existing_key = ""
                                    if loc_guid:
                                        loc_comp = parser.find_component_by_guid(go_id, loc_guid)
                                        if loc_comp:
                                            existing_key = parser.get_string_id_from_loc(loc_comp)
                                    
                                    go_name = parser.get_property(go_id, "m_Name") or f"GameObject_{go_id}"
                                    if go_name.startswith('"'):
                                        go_name = go_name[1:-1]

                                    results.append({
                                        "Prefab Path": os.path.relpath(prefab_path, scan_path),
                                        "GameObject Name": go_name,
                                        "GameObject ID": go_id,
                                        "Original Text": text_val,
                                        "KeyId": existing_key
                                    })
                                    file_text_count += 1
                                    text_found_count += 1
                    
                    if file_text_count > 0:
                        self.log(f"  ✓ {file_name}: 找到 {file_text_count} 个文本")

                except Exception as e:
                    self.log(f"  ❌ 错误 {file_name}: {e}")
                
                # 更新进度 (每个文件都更新)
                progress_pct = int((i + 1) / total_count * 100)
                self.update_progress(i + 1)
                self.update_status(f"扫描中... {i + 1}/{total_count} ({progress_pct}%)")
            
            self.log("-" * 40)
            self.log(f"扫描完成! 共找到 {text_found_count} 个文本组件")
            
            # Export
            if not results:
                self.log("⚠️ 未找到任何文本，跳过导出")
                self.update_status("完成 - 未找到文本")
                self.update_progress(0)
                self.root.after(0, lambda: messagebox.showwarning("提示", "未在所选Prefab中找到任何Text组件"))
                return
            
            self.log("正在导出CSV...")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_file = os.path.join(export_path, f"PrefabExport_{timestamp}.csv")
            
            try:
                with open(out_file, 'w', newline='', encoding='utf-8-sig') as f:
                    fieldnames = ["Prefab Path", "GameObject Name", "GameObject ID", "Original Text", "KeyId"]
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(results)
                self.log(f"✅ 导出成功!")
                self.log(f"   文件: {out_file}")
                self.log(f"   记录数: {len(results)}")
                self.root.after(0, lambda: messagebox.showinfo("成功", f"导出完成!\n\n文件: {out_file}\n共 {len(results)} 条记录"))
            except Exception as e:
                self.log(f"❌ 保存失败: {e}")
                self.root.after(0, lambda: messagebox.showerror("错误", f"保存失败: {e}"))
            
            self.update_progress(0)
            self.update_status("就绪")
            
        except Exception as e:
            self.log(f"❌ 扫描过程出错: {e}")
            import traceback
            self.log(traceback.format_exc())
            self.update_status("出错")
            self.root.after(0, lambda: messagebox.showerror("错误", f"扫描失败: {e}"))

    # --- Patch ---
    def start_patch_thread(self):
        self.save_config()
        
        if not self.import_file.get():
            messagebox.showerror("错误", "请先选择要导入的CSV文件")
            return
        
        threading.Thread(target=self.run_patch, daemon=True).start()

    def run_patch(self):
        file_path = self.import_file.get()
        scan_path = self.scan_dir.get()
        loc_guid = self.loc_guid.get()
        
        if not os.path.exists(file_path):
            self.log("错误: 文件不存在")
            return
        
        if not scan_path or not os.path.exists(scan_path):
            self.log("错误: 请先设置有效的扫描目录(用于定位Prefab)")
            return
        
        self.log("=" * 40)
        self.log(f"读取 {os.path.basename(file_path)}...")
        self.update_status("读取文件...")
        
        tasks = {}
        
        try:
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            
            count = 0
            for row in rows:
                p_path = (row.get("Prefab Path") or "").strip()
                raw_key = (row.get("KeyId") or "").strip()
                go_id = (row.get("GameObject ID") or "").strip()
                go_name = (row.get("GameObject Name") or "").strip()
                
                # Clean KeyId (remove .0 suffix from float conversion)
                key_id = raw_key[:-2] if raw_key.endswith(".0") else raw_key
                
                if p_path and key_id and go_id:
                    if p_path not in tasks:
                        tasks[p_path] = []
                    tasks[p_path].append({
                        'go_id': go_id,
                        'key_id': key_id,
                        'go_name': go_name
                    })
                    count += 1
            
            self.log(f"加载 {count} 条待处理记录")
            
        except Exception as e:
            self.log(f"读取文件失败: {e}")
            return

        total_tasks = len(tasks)
        self.update_progress(0, total_tasks)
        processed = 0
        
        # 收集所有需要处理的文件路径
        files_to_process = []
        for rel_path in tasks.keys():
            full_path = os.path.join(scan_path, rel_path)
            if os.path.exists(full_path):
                files_to_process.append((rel_path, full_path))
            else:
                self.log(f"⚠️ 跳过: 文件不存在 - {rel_path}")
        
        # 如果启用了P4，先批量checkout所有文件
        if self.p4_enabled.get() and files_to_process:
            self.log("-" * 40)
            self.log(f"[P4] 开始批量Checkout {len(files_to_process)} 个文件...")
            self.update_status("P4 Checkout...")
            
            for rel_path, full_path in files_to_process:
                self.p4_checkout(full_path)
            
            self.log("[P4] Checkout完成")
            self.log("-" * 40)
        
        self.log(f"开始处理 {len(files_to_process)} 个文件...")
        
        for rel_path, full_path in files_to_process:
            items = tasks[rel_path]
            
            try:
                self.patch_prefab(full_path, items, loc_guid)
            except Exception as e:
                self.log(f"❌ 处理失败 {rel_path}: {e}")
                import traceback
                self.log(traceback.format_exc())
            
            processed += 1
            progress_pct = int(processed / len(files_to_process) * 100)
            self.update_progress(processed)
            self.update_status(f"处理中... {processed}/{len(files_to_process)} ({progress_pct}%)")

        # --- Entities export: create versioned daydream-entities csv ---
        entities_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "EntitiesExport")
        new_entity_rows = []

        new_key_source_rows = [r for r in rows if (r.get("KeySource") or "").strip() == "\u65b0\u589e"]

        if new_key_source_rows:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for r in new_key_source_rows:
                key_id = (r.get("KeyId") or "").strip()
                if not key_id:
                    continue
                original_text = (r.get("Original Text") or "").strip()
                has_chinese = bool(re.search(r'[\u4e00-\u9fff]', original_text))
                english_val = "" if has_chinese else original_text
                chinese_val = original_text if has_chinese else ""
                new_entity_rows.append({
                    "Key": key_id,
                    "Content": english_val,
                    "Content(English)_update_time": now_str if english_val else "",
                    "Word Count": len(original_text),
                    "Context": (r.get("Prefab Path") or "").strip(),
                    "Original": chinese_val,
                    "Original(Chinese Simplified)_update_time": now_str if chinese_val else "",
                })

        entities_exported = 0
        entities_file_path = ""
        if new_entity_rows:
            try:
                if not os.path.exists(entities_dir):
                    os.makedirs(entities_dir)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                entities_filename = f"daydream-entities_{timestamp}.csv"
                entities_file_path = os.path.join(entities_dir, entities_filename)
                fieldnames = ["Key", "Content", "Content(English)_update_time",
                              "Word Count", "Context", "Original",
                              "Original(Chinese Simplified)_update_time"]
                with open(entities_file_path, 'w', newline='', encoding='utf-8-sig') as ef:
                    writer = csv.DictWriter(ef, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(new_entity_rows)
                entities_exported = len(new_entity_rows)
                self.log(f"  entities: {entities_exported} new keys exported")
                self.log(f"  entities file: {entities_file_path}")
            except Exception as e:
                self.log(f"  entities export fail: {e}")

        self.log("=" * 40)
        self.log("processing done!")
        if entities_exported > 0:
            self.log(f"  entities exported: {entities_exported} keys")
            self.log(f"  entities path: EntitiesExport/{os.path.basename(entities_file_path)}")
        else:
            self.log(f"  entities: no new keys to export")
        self.update_progress(0)
        self.update_status("\u5c31\u7eea")

        summary = f"Prefab\u5904\u7406\u5b8c\u6210!\n\n"
        summary += f"\u5904\u7406\u6587\u4ef6: {len(files_to_process)} \u4e2a\n"
        if entities_exported > 0:
            summary += f"\n\u65b0\u589eEntities\u5bfc\u51fa: {entities_exported} \u4e2aKey\n"
            summary += f"\u5bfc\u51fa\u6587\u4ef6: {os.path.basename(entities_file_path)}\n"
            summary += f"\u5bfc\u51fa\u8def\u5f84: {entities_dir}"
        else:
            summary += f"\n\u65e0\u65b0\u589eKey\u9700\u8981\u5bfc\u51fa"
        self.root.after(0, lambda: messagebox.showinfo("\u5b8c\u6210", summary))

    def patch_prefab(self, file_path, items, loc_guid):
        self.log(f"--- 处理 {os.path.basename(file_path)} ---")
        self.log(f"  待处理条目: {len(items)} 个")
        self.log(f"  LocComponent GUID: {loc_guid}")
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            self.log(f"  ❌ 读取失败: {e}")
            return
        
        original_content = content  # 保存原始内容用于比较
        
        ids = [int(x) for x in re.findall(r'&(\d+)', content)]
        max_id = max(ids) if ids else 10000
        self.log(f"  文件中最大ID: {max_id}")
        
        modified = False
        success_count = 0
        skip_count = 0
        error_count = 0
        
        for item in items:
            go_id = str(item['go_id']).strip()
            key_id = str(item['key_id']).strip() if item['key_id'] else ""
            go_name = item.get('go_name', 'Unknown')
            
            self.log(f"  处理: {go_name} (ID:{go_id}, Key:{key_id})")
            
            if not key_id:
                self.log(f"    ⚠️ 跳过: KeyId为空")
                skip_count += 1
                continue
            
            # Handle scientific notation
            if "E+" in go_id or "e+" in go_id.lower():
                try:
                    approx_id_str = str(int(float(go_id)))
                    base_num = go_id.upper().split("E")[0].replace(".", "")
                    id_prefix = approx_id_str[:len(base_num)]
                    
                    self.log(f"    科学计数法转换: {go_id} -> 前缀 {id_prefix}")
                    
                    all_go_matches = re.findall(r'^--- !u!1 &(\d+)', content, re.MULTILINE)
                    candidates = [mid for mid in all_go_matches if mid.startswith(id_prefix)]
                    
                    if len(candidates) == 1:
                        go_id = candidates[0]
                        self.log(f"    恢复ID: {go_id}")
                    elif len(candidates) > 1:
                        self.log(f"    ❌ 多个匹配候选: {candidates}")
                        error_count += 1
                        continue
                    else:
                        self.log(f"    ❌ 无匹配候选")
                        error_count += 1
                        continue
                except ValueError as e:
                    self.log(f"    ❌ ID转换失败: {e}")
                    error_count += 1
                    continue
            
            # 检查 GameObject 是否存在
            go_pattern = rf'^--- !u!1 &{go_id}\b'
            if not re.search(go_pattern, content, re.MULTILINE):
                self.log(f"    ❌ 找不到GameObject定义: &{go_id}")
                error_count += 1
                continue
            
            # Check for existing LocComponent
            block_pattern = re.compile(r'--- !u!114 &(\d+)\nMonoBehaviour:.*?(?=--- !u!|\Z)', re.DOTALL)
            
            existing_comp_id = None
            existing_comp_content = None
            
            for match in block_pattern.finditer(content):
                block_content = match.group(0)
                if f"m_GameObject: {{fileID: {go_id}}}" in block_content and \
                   f"guid: {loc_guid}" in block_content:
                    existing_comp_id = match.group(1)
                    existing_comp_content = block_content
                    break
            
            clean_key = key_id.replace('"', '')
            if clean_key.endswith('.0'):
                clean_key = clean_key[:-2]
            
            if existing_comp_id:
                self.log(f"    已有LocComponent: &{existing_comp_id}")
                new_block = re.sub(r'StringID:.*', f'StringID: {clean_key}', existing_comp_content)
                new_block = re.sub(r'LanguageFunc: 0', 'LanguageFunc: 1', new_block)
                
                if new_block != existing_comp_content:
                    content = content.replace(existing_comp_content, new_block)
                    modified = True
                    success_count += 1
                    self.log(f"    ✓ 更新StringID: {clean_key}")
                else:
                    self.log(f"    ℹ️ 已是最新，无需更新")
                    skip_count += 1
            else:
                self.log(f"    创建新LocComponent...")
                max_id += 1
                new_comp_id = max_id
                
                # 创建新组件 YAML
                new_comp_yaml = f"""
--- !u!114 &{new_comp_id}
MonoBehaviour:
  m_ObjectHideFlags: 0
  m_CorrespondingSourceObject: {{fileID: 0}}
  m_PrefabInstance: {{fileID: 0}}
  m_PrefabAsset: {{fileID: 0}}
  m_GameObject: {{fileID: {go_id}}}
  m_Enabled: 1
  m_EditorHideFlags: 0
  m_Script: {{fileID: 11500000, guid: {loc_guid}, type: 3}}
  m_Name: 
  m_EditorClassIdentifier: 
  StringID: {clean_key}
  parameters: []
  FontSetName: 
  LocType: 
  SpriteName: 
  AtlasName: 
  ChangeFontOnly: 0
  LanguageFunc: 1
  formatProvider: 
  Global: {{fileID: 0}}
"""
                content += new_comp_yaml
                self.log(f"    创建组件 &{new_comp_id}")
                
                # 添加组件引用到 GameObject
                go_header_pattern = re.compile(rf'^--- !u!1 &{go_id}\b', re.MULTILINE)
                go_match = go_header_pattern.search(content)
                
                if go_match:
                    go_start_idx = go_match.start()
                    go_end_idx = content.find("--- !u!", go_start_idx + 1)
                    if go_end_idx == -1:
                        go_end_idx = len(content)
                    
                    go_block = content[go_start_idx:go_end_idx]
                    self.log(f"    GameObject块长度: {len(go_block)}")
                    
                    comp_idx = content.find("m_Component:", go_start_idx, go_end_idx)
                    
                    if comp_idx != -1:
                        # 找到 m_Component: 后的第一行结束位置
                        insert_pos = content.find("\n", comp_idx) + 1
                        ref_line = f"  - component: {{fileID: {new_comp_id}}}\n"
                        content = content[:insert_pos] + ref_line + content[insert_pos:]
                        modified = True
                        success_count += 1
                        self.log(f"    ✓ 添加组件引用到GameObject")
                    else:
                        self.log(f"    ❌ 找不到m_Component列表")
                        error_count += 1
                else:
                    self.log(f"    ❌ 找不到GameObject块")
                    error_count += 1

        self.log(f"  统计: 成功={success_count}, 跳过={skip_count}, 失败={error_count}")
        
        if modified and content != original_content:
            try:
                with open(file_path, 'w', encoding='utf-8', newline='\n') as f:
                    f.write(content)
                self.log(f"  ✅ 已保存文件")
            except PermissionError:
                self.log(f"  ❌ 保存失败: 文件只读或被锁定，请确保已P4 Checkout")
            except Exception as e:
                self.log(f"  ❌ 保存失败: {e}")
                import traceback
                self.log(traceback.format_exc())
        else:
            self.log("  ℹ️ 无需修改文件")


if __name__ == "__main__":
    print("=" * 50)
    print("Unity Prefab Text Extractor - 启动中...")
    print("=" * 50)
    
    try:
        print("[1/3] 初始化 Tkinter...")
        root = tk.Tk()
        
        print("[2/3] 创建应用程序...")
        app = PrefabTextExtractor(root)
        
        print("[3/3] 窗口已创建，正在显示...")
        print("")
        print("提示: 如果看不到窗口，请检查任务栏或 Alt+Tab 切换")
        print("关闭窗口后程序将退出")
        print("-" * 50)
        
        # 确保窗口在最前面
        root.lift()
        root.attributes('-topmost', True)
        root.after(100, lambda: root.attributes('-topmost', False))
        root.focus_force()
        
        root.mainloop()
        print("程序正常退出")
        
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
        input("\n按回车键退出...")
