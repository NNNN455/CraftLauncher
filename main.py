import customtkinter as ctk
import minecraft_launcher_lib
import subprocess
import os
import json
import threading
import re
import io
import sys
import requests
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from tkinter import messagebox
from PIL import Image

# ============ НАСТРОЙКИ ============
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")

APPDATA = os.getenv("APPDATA") or os.path.expanduser("~")
LAUNCHER_DIR = os.path.join(APPDATA, ".CraftLauncher")
INSTANCES_DIR = os.path.join(LAUNCHER_DIR, "instances")
CONFIG_FILE = os.path.join(LAUNCHER_DIR, "config.json")
LOG_FILE = os.path.join(LAUNCHER_DIR, "launcher.log")

AUTHLIB_JAR = os.path.join(LAUNCHER_DIR, "authlib-injector.jar")
AUTHLIB_URL = "https://github.com/yushijinhun/authlib-injector/releases/latest/download/authlib-injector.jar"

ELY_AUTH_URL = "https://authserver.ely.by/auth/authenticate"
ELY_SKIN_URL = "http://skinsystem.ely.by/skins/{nickname}.png"

MODRINTH_API = "https://api.modrinth.com/v2"
USER_AGENT = "CraftLauncher/0.99"

os.makedirs(LAUNCHER_DIR, exist_ok=True)
os.makedirs(INSTANCES_DIR, exist_ok=True)


def get_resource_path(filename):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, filename)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)


ICON_PATH = get_resource_path("icon.ico")


def log(msg, level="INFO"):
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [{level}] {msg}\n")
    except Exception:
        pass


log("=" * 60)
log("CraftLauncher v0.99 started")


# ============ RAM ============
try:
    import psutil

    def get_ram_limits():
        total_mb = int(psutil.virtual_memory().total / (1024 * 1024))
        max_ram = max(1024, ((total_mb - 1024) // 256) * 256)
        return 512, max_ram, total_mb

    RAM_MIN, RAM_MAX, RAM_TOTAL = get_ram_limits()
    log(f"RAM: {RAM_TOTAL} MB")
except ImportError:
    RAM_MIN, RAM_MAX, RAM_TOTAL = 512, 8192, 8192
    log("psutil not installed", "WARN")


# ============ VPN ============
def get_vpn_ip():
    try:
        result = subprocess.run(["ipconfig"], capture_output=True, text=True,
                                 encoding="cp866", errors="replace",
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        lines = result.stdout.split("\n")

        for i, line in enumerate(lines):
            if "Radmin VPN" in line or "Radmin" in line:
                for j in range(i, min(i + 15, len(lines))):
                    if "IPv4" in lines[j] or "IP-адрес" in lines[j] or "IP Address" in lines[j]:
                        parts = lines[j].strip().split(":")
                        if len(parts) >= 2:
                            ip = parts[-1].strip().split()[0]
                            if "." in ip and not ip.startswith("127."):
                                return ip, "Radmin VPN"

        for i, line in enumerate(lines):
            if "Hamachi" in line:
                for j in range(i, min(i + 15, len(lines))):
                    if "IPv4" in lines[j] or "IP-адрес" in lines[j] or "IP Address" in lines[j]:
                        parts = lines[j].strip().split(":")
                        if len(parts) >= 2:
                            ip = parts[-1].strip().split()[0]
                            if "." in ip and not ip.startswith("127."):
                                return ip, "Hamachi"

        for line in lines:
            if ("IPv4" in line or "IP-адрес" in line) and ("25." in line or "5." in line):
                parts = line.strip().split(":")
                if len(parts) >= 2:
                    ip = parts[-1].strip().split()[0]
                    if ip.startswith("25."):
                        return ip, "Radmin VPN"
                    elif ip.startswith("5."):
                        return ip, "Hamachi"
    except Exception as e:
        log(f"VPN scan: {e}", "ERROR")
    return None, None


# ============ КАТЕГОРИИ MODRINTH ============
MODRINTH_CATEGORIES = [
    "Все категории",
    "adventure",       # приключения
    "cursed",          # хоррор / странное
    "decoration",      # декорации
    "economy",         # экономика
    "equipment",       # снаряжение
    "food",            # еда
    "game-mechanics",  # игровая механика
    "library",         # библиотеки
    "magic",           # магия
    "mobs",            # мобы
    "optimization",    # оптимизация
    "social",          # социальное
    "storage",         # хранение
    "technology",      # технологии
    "transportation",  # транспорт
    "utility",         # утилиты
    "worldgen",        # генерация мира
]

# Русские названия для категорий
CATEGORY_LABELS = {
    "Все категории": "Все категории",
    "adventure": "🏔 Приключения",
    "cursed": "👻 Хоррор",
    "decoration": "🎨 Декорации",
    "economy": "💰 Экономика",
    "equipment": "⚔ Снаряжение",
    "food": "🍔 Еда",
    "game-mechanics": "🎮 Механика",
    "library": "📚 Библиотеки",
    "magic": "🔮 Магия",
    "mobs": "🐉 Мобы",
    "optimization": "⚡ Оптимизация",
    "social": "👥 Социальное",
    "storage": "📦 Хранилище",
    "technology": "⚙ Технологии",
    "transportation": "🚗 Транспорт",
    "utility": "🔧 Утилиты",
    "worldgen": "🌍 Генерация мира",
}

CATEGORY_LABELS_REVERSE = {v: k for k, v in CATEGORY_LABELS.items()}


# ============ MODRINTH ============
def search_modrinth_mods_advanced(query="", mc_version=None, category=None,
                                    limit=20, index="downloads"):
    """
    Расширенный поиск модов.
    index: "downloads" (популярные), "relevance" (релевантность),
           "newest" (новые), "updated" (обновлённые)
    """
    try:
        facets = [["project_type:mod"]]
        if mc_version:
            facets.append([f"versions:{mc_version}"])
        if category and category != "Все категории":
            facets.append([f"categories:{category}"])

        params = {
            "limit": limit,
            "index": index,
            "facets": json.dumps(facets),
        }
        # Если запрос пустой — поиск популярных
        if query:
            params["query"] = query

        headers = {"User-Agent": USER_AGENT}
        response = requests.get(f"{MODRINTH_API}/search", params=params,
                                 headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        log(f"Modrinth: query='{query}' cat='{category}' → {len(data.get('hits', []))}")
        return data.get("hits", [])
    except Exception as e:
        log(f"Modrinth search error: {e}", "ERROR")
        return []


def get_modrinth_versions(project_id, mc_version, mod_loader=None):
    try:
        params = {"game_versions": json.dumps([mc_version])}
        if mod_loader:
            params["loaders"] = json.dumps([mod_loader])
        headers = {"User-Agent": USER_AGENT}
        response = requests.get(f"{MODRINTH_API}/project/{project_id}/version",
                                 params=params, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        log(f"Modrinth versions error: {e}", "ERROR")
        return []


def get_mod_dependencies(project_id, mc_version):
    try:
        versions = get_modrinth_versions(project_id, mc_version)
        if not versions:
            return []
        version = versions[0]
        deps = version.get("dependencies", [])
        required = []
        for dep in deps:
            if dep.get("dependency_type") == "required":
                required.append({
                    "project_id": dep.get("project_id"),
                    "version_id": dep.get("version_id"),
                    "file_name": dep.get("file_name", "unknown"),
                })
        return required
    except Exception as e:
        log(f"get_mod_dependencies error: {e}", "ERROR")
        return []


def install_mod_from_modrinth(instance_name, project_id, mc_version, _visited=None):
    if _visited is None:
        _visited = set()
    if project_id in _visited:
        return True, "Уже установлен"
    _visited.add(project_id)

    try:
        versions = get_modrinth_versions(project_id, mc_version)
        if not versions:
            return False, f"Нет версии для MC {mc_version}"

        version = versions[0]
        files = version.get("files", [])
        primary = None
        for f in files:
            if f.get("primary") and f["filename"].endswith(".jar"):
                primary = f
                break
        if not primary:
            for f in files:
                if f["filename"].endswith(".jar"):
                    primary = f
                    break
        if not primary:
            return False, "JAR не найден"

        deps = version.get("dependencies", [])
        required_deps = [d for d in deps if d.get("dependency_type") == "required"]
        log(f"Dependencies of {project_id}: {len(required_deps)} required")

        for dep in required_deps:
            dep_project_id = dep.get("project_id")
            if not dep_project_id:
                continue
            install_mod_from_modrinth(
                instance_name, dep_project_id, mc_version, _visited
            )

        mods_dir = os.path.join(instance_minecraft_dir(instance_name), "mods")
        os.makedirs(mods_dir, exist_ok=True)
        filepath = os.path.join(mods_dir, primary["filename"])

        r = requests.get(primary["url"], timeout=60,
                         headers={"User-Agent": USER_AGENT}, stream=True)
        r.raise_for_status()
        with open(filepath, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

        log(f"Mod installed: {primary['filename']}")
        return True, primary["filename"]
    except Exception as e:
        log(f"Install mod error: {e}", "ERROR")
        return False, str(e)


def download_mod_icon(icon_url):
    if not icon_url:
        return None
    try:
        headers = {"User-Agent": USER_AGENT}
        r = requests.get(icon_url, timeout=10, headers=headers)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert("RGBA")
        return img
    except Exception as e:
        log(f"Icon download error: {e}", "WARN")
        return None


# ============ ЗАГРУЗЧИКИ МОДОВ ============
def get_available_loader_versions(loader_id, mc_version):
    try:
        if loader_id == "forge":
            versions = minecraft_launcher_lib.forge.list_forge_versions()
            prefix = f"{mc_version}-"
            result = [v for v in versions if v.startswith(prefix)]
            return sorted(result, key=version_sort_key, reverse=True)
        elif loader_id == "fabric":
            try:
                latest = minecraft_launcher_lib.fabric.get_latest_loader_version()
                return [latest]
            except Exception:
                return []
    except Exception as e:
        log(f"get_available_loader_versions: {e}", "ERROR")
    return []


def install_loader_to_instance(instance_name, loader_id, mc_version, loader_version=None, status_callback=None):
    mc_dir = instance_minecraft_dir(instance_name)

    def status(msg):
        log(f"[loader] {msg}")
        if status_callback:
            try:
                status_callback(msg)
            except Exception:
                pass

    try:
        status(f"Проверка ванильной версии {mc_version}...")
        minecraft_launcher_lib.install.install_minecraft_version(
            mc_version, mc_dir,
            callback={"setStatus": lambda s: status(s[:60])}
        )

        if loader_id == "forge":
            if not loader_version:
                available = get_available_loader_versions("forge", mc_version)
                if not available:
                    return False, f"Forge не поддерживает MC {mc_version}"
                loader_version = available[0]

            status(f"Найден Forge: {loader_version}")

            choice = messagebox.askyesnocancel(
                "⚙ Установка Forge",
                f"Forge — небольшая команда, которая много сделала\n"
                f"для Minecraft. Их проект живёт за счёт рекламы\n"
                f"на официальной странице загрузки.\n\n"
                f"Разработчики просят НЕ автоматизировать установку.\n\n"
                f"Как поступим?\n\n"
                f"✅ ДА — открыть официальный установщик\n"
                f"   (поддержишь Forge, 2-3 клика вручную)\n\n"
                f"❌ НЕТ — установить автоматически\n"
                f"   (быстро, но без поддержки проекта)\n\n"
                f"⚠ Отмена — не устанавливать"
            )

            if choice is None:
                status("Установка отменена пользователем")
                return False, "Отменено"

            elif choice:
                status("Запуск официального установщика Forge...")
                messagebox.showinfo(
                    "📋 Инструкция",
                    f"Сейчас откроется официальный установщик Forge.\n\n"
                    f"1️⃣ Выбери «Install client»\n\n"
                    f"2️⃣ Укажи путь к папке игры:\n"
                    f"{mc_dir}\n\n"
                    f"3️⃣ Нажми OK и дождись завершения.\n\n"
                    f"⚠ НЕ закрывай установщик до конца!\n\n"
                    f"После завершения — нажми «Играть» в лаунчере."
                )
                try:
                    minecraft_launcher_lib.forge.run_forge_installer(loader_version)
                    status("Официальный установщик запущен")
                    return False, "Ручная установка запущена. Заверши в установщике."
                except Exception as e:
                    log(f"run_forge_installer error: {e}", "ERROR")
                    status(f"❌ Ошибка запуска: {e}")
                    return False, f"Ошибка: {e}"
            else:
                status("Автоматическая установка Forge...")
                try:
                    supports_auto = minecraft_launcher_lib.forge.supports_automatic_install(loader_version)
                except Exception:
                    supports_auto = False

                if not supports_auto:
                    messagebox.showwarning(
                        "⚠ Требуется ручная установка",
                        f"Forge {loader_version} не поддерживает\n"
                        f"автоматическую установку.\n\n"
                        f"Откроется официальный установщик.\n"
                        f"Выбери «Install client» и укажи путь:\n\n"
                        f"{mc_dir}"
                    )
                    try:
                        minecraft_launcher_lib.forge.run_forge_installer(loader_version)
                        return False, "Ручная установка (старая версия Forge)"
                    except Exception as e:
                        log(f"run_forge_installer error: {e}", "ERROR")
                        return False, f"Ошибка: {e}"

                minecraft_launcher_lib.forge.install_forge_version(
                    loader_version, mc_dir,
                    callback={"setStatus": lambda s: status(s[:60])}
                )

                try:
                    installed_id = minecraft_launcher_lib.forge.forge_to_installed_version(loader_version)
                except Exception:
                    installed_id = loader_version

                status(f"✅ Forge установлен: {installed_id}")
                return True, installed_id

        elif loader_id == "fabric":
            if not loader_version:
                loader_version = minecraft_launcher_lib.fabric.get_latest_loader_version()

            status(f"Установка Fabric {loader_version}...")
            minecraft_launcher_lib.fabric.install_fabric(
                mc_version, mc_dir, loader_version=loader_version,
                callback={"setStatus": lambda s: status(s[:60])}
            )
            installed_id = f"fabric-loader-{loader_version}-{mc_version}"
            status(f"✅ Fabric установлен: {installed_id}")
            return True, installed_id

        else:
            return False, f"Неизвестный загрузчик: {loader_id}"

    except Exception as e:
        log(f"install_loader_to_instance error: {e}", "ERROR")
        status(f"❌ Ошибка: {str(e)[:60]}")
        return False, str(e)


# ============ УТИЛИТЫ ============
def version_sort_key(v):
    nums = re.findall(r'\d+', v)
    if not nums:
        return (0,)
    return tuple(int(n) for n in nums)


def sort_versions(versions):
    return sorted(versions, key=version_sort_key, reverse=True)


def set_icon(window):
    if os.path.exists(ICON_PATH):
        try:
            window.iconbitmap(ICON_PATH)
        except Exception:
            pass


def download_authlib():
    if os.path.exists(AUTHLIB_JAR):
        return True
    try:
        log("Downloading authlib-injector.jar...")
        urllib.request.urlretrieve(AUTHLIB_URL, AUTHLIB_JAR)
        return True
    except Exception as e:
        log(f"authlib download: {e}", "ERROR")
        return False


def load_skin_image(nickname):
    if not nickname:
        return None
    try:
        url = ELY_SKIN_URL.format(nickname=nickname)
        req = urllib.request.Request(url, headers={'User-Agent': 'CraftLauncher/0.99'})
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                img = Image.open(io.BytesIO(response.read()))
                return img.convert("RGBA")
    except Exception:
        pass
    return None


def crop_head_from_skin(img):
    try:
        w, h = img.size
        if w >= 64 and h >= 64:
            head = img.crop((8, 8, 16, 16))
            try:
                overlay = img.crop((40, 8, 48, 16))
                head = Image.alpha_composite(head.convert("RGBA"), overlay.convert("RGBA"))
            except Exception:
                pass
            return head.resize((64, 64), Image.NEAREST)
        else:
            size = min(w, h)
            return img.crop((0, 0, size, size)).resize((64, 64), Image.NEAREST)
    except Exception:
        return img.resize((64, 64), Image.LANCZOS)


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                cfg.pop("ely_token", None)
                cfg.pop("ely_uuid", None)
                cfg.pop("ely_username", None)
                return cfg
        except Exception:
            pass
    return {
        "nickname": "Steve",
        "appearance": "dark",
        "auto_launch_after_install": True,
        "show_console": True,
        "window_geometry": "1100x740+100+100",
        "last_server_ip": "",
    }


def save_config(cfg):
    try:
        cfg.pop("ely_token", None)
        cfg.pop("ely_uuid", None)
        cfg.pop("ely_username", None)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
    except Exception:
        pass


def ely_authenticate(username, password, twofa_code=""):
    try:
        if twofa_code:
            password = f"{password}:{twofa_code}"
        data = urllib.parse.urlencode({
            "username": username, "password": password,
            "clientToken": "CraftLauncher", "requestUser": "true"
        }).encode("utf-8")
        req = urllib.request.Request(ELY_AUTH_URL, data=data)
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
            if "accessToken" in result and "selectedProfile" in result:
                return {
                    "accessToken": result["accessToken"],
                    "uuid": result["selectedProfile"]["id"],
                    "name": result["selectedProfile"]["name"]
                }
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        log(f"Ely auth HTTP error: {e.code}", "ERROR")
        if "2FA" in error_body or "two" in error_body.lower():
            return "NEED_2FA"
    except Exception as e:
        log(f"Ely auth: {e}", "ERROR")
    return None


# ============ ЭКЗЕМПЛЯРЫ ============
def instance_path(name):
    return os.path.join(INSTANCES_DIR, name)


def instance_minecraft_dir(name):
    return os.path.join(instance_path(name), "minecraft")


def instance_config_path(name):
    return os.path.join(instance_path(name), "instance.json")


def is_version_installed(instance_name, version):
    try:
        mc_dir = instance_minecraft_dir(instance_name)
        vdir = os.path.join(mc_dir, "versions", version)
        return (os.path.exists(os.path.join(vdir, f"{version}.json")) and
                os.path.exists(os.path.join(vdir, f"{version}.jar")))
    except Exception:
        return False


def list_instances():
    result = []
    if not os.path.exists(INSTANCES_DIR):
        return result
    for name in sorted(os.listdir(INSTANCES_DIR)):
        cfg_path = instance_config_path(name)
        if os.path.isdir(instance_path(name)) and os.path.exists(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    data.setdefault("ram", 2048)
                    data.setdefault("mod_loader", "vanilla")
                    data.setdefault("launch_version", data.get("version", ""))
                    result.append(data)
            except Exception:
                pass
    return result


def create_instance(name, version, ram=2048, mod_loader="vanilla", launch_version=None):
    mpath = instance_minecraft_dir(name)
    os.makedirs(mpath, exist_ok=True)
    data = {
        "name": name,
        "version": version,
        "launch_version": launch_version or version,
        "mod_loader": mod_loader,
        "ram": ram,
        "created": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    with open(instance_config_path(name), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    return data


def save_instance_config(name, data):
    with open(instance_config_path(name), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def delete_instance(name):
    import shutil
    shutil.rmtree(instance_path(name), ignore_errors=True)


# ============ МОД-БРАУЗЕР (с фильтрами) ============
class ModsWindow(ctk.CTkToplevel):
    def __init__(self, parent, instance_name, mc_version):
        super().__init__(parent)
        self.parent = parent
        self.instance_name = instance_name
        self.mc_version = mc_version
        self.grab_set()
        self.after(100, self.lift)
        set_icon(self)

        self.title(f"Моды для {instance_name}")
        self.geometry("820x850")
        self.minsize(760, 640)

        self.installed_mods = set()
        self._icon_refs = []

        # Заголовок
        ctk.CTkLabel(self, text="🧩  Мод-браузер",
                     font=("Arial", 22, "bold"),
                     text_color="#4CAF50").pack(pady=(20, 3))
        ctk.CTkLabel(self, text=f"Экземпляр: {instance_name}  ·  Minecraft {mc_version}",
                     font=("Arial", 11), text_color="gray").pack(pady=(0, 15))

        # === ПОИСК + ФИЛЬТР ===
        search_row = ctk.CTkFrame(self, fg_color="transparent")
        search_row.pack(fill="x", padx=25, pady=(0, 5))

        ctk.CTkLabel(search_row, text="🔍",
                     font=("Arial", 16)).pack(side="left", padx=(0, 5))
        self.search_entry = ctk.CTkEntry(
            search_row, height=38, font=("Arial", 13),
            placeholder_text="Название мода (оставь пусто — покажет популярные)")
        self.search_entry.pack(side="left", fill="x", expand=True)
        self.search_entry.bind("<Return>", lambda e: self.search())

        self.search_btn = ctk.CTkButton(
            search_row, text="Найти", width=100, height=38,
            font=("Arial", 12, "bold"),
            fg_color="#4CAF50", hover_color="#3d8b40",
            command=self.search)
        self.search_btn.pack(side="left", padx=(8, 0))

        # === ФИЛЬТРЫ ===
        filter_row = ctk.CTkFrame(self, fg_color="transparent")
        filter_row.pack(fill="x", padx=25, pady=(5, 10))

        ctk.CTkLabel(filter_row, text="Категория:",
                     font=("Arial", 11), text_color="gray").pack(side="left", padx=(0, 5))

        self.category_var = ctk.StringVar(value=CATEGORY_LABELS["Все категории"])
        category_values = [CATEGORY_LABELS[c] for c in MODRINTH_CATEGORIES]
        self.category_menu = ctk.CTkOptionMenu(
            filter_row, variable=self.category_var,
            values=category_values, width=220, height=32,
            font=("Arial", 11),
            command=lambda _: self.search()
        )
        self.category_menu.pack(side="left", padx=(0, 15))

        ctk.CTkLabel(filter_row, text="Сортировка:",
                     font=("Arial", 11), text_color="gray").pack(side="left", padx=(0, 5))

        self.sort_var = ctk.StringVar(value="📥 По популярности")
        self.sort_menu = ctk.CTkOptionMenu(
            filter_row, variable=self.sort_var,
            values=["📥 По популярности", "🆕 Новые", "🔥 Обновлённые", "🎯 По релевантности"],
            width=180, height=32, font=("Arial", 11),
            command=lambda _: self.search()
        )
        self.sort_menu.pack(side="left")

        # Статус
        self.status_label = ctk.CTkLabel(
            self, text="Введи название или выбери категорию",
            font=("Arial", 11), text_color="gray")
        self.status_label.pack(pady=(5, 10))

        # Список
        self.scroll = ctk.CTkScrollableFrame(
            self, fg_color=("gray90", "gray15"),
            width=770, height=580)
        self.scroll.pack(padx=25, pady=(0, 15), fill="both", expand=True)

        # Кнопки внизу
        bottom_frame = ctk.CTkFrame(self, fg_color="transparent")
        bottom_frame.pack(pady=(0, 15), fill="x", padx=25)

        ctk.CTkButton(bottom_frame, text="📂 Открыть папку модов", height=36,
                      font=("Arial", 12), fg_color="#555", hover_color="#333",
                      command=self.open_mods_folder).pack(side="left", expand=True,
                                                            fill="x", padx=(0, 5))
        ctk.CTkButton(bottom_frame, text="🔄 Обновить", height=36,
                      font=("Arial", 12), fg_color="#555", hover_color="#333",
                      command=self.refresh_installed).pack(side="left", expand=True,
                                                             fill="x", padx=(0, 5))
        ctk.CTkButton(bottom_frame, text="Закрыть", height=36,
                      font=("Arial", 12), fg_color="#4CAF50", hover_color="#3d8b40",
                      command=self.destroy).pack(side="left", expand=True,
                                                  fill="x", padx=(5, 0))

        self.refresh_installed()

        # Автозагрузка популярных при открытии
        self.after(300, self.load_popular)

    def open_mods_folder(self):
        mods_dir = os.path.join(instance_minecraft_dir(self.instance_name), "mods")
        os.makedirs(mods_dir, exist_ok=True)
        os.startfile(mods_dir)

    def refresh_installed(self):
        mods_dir = os.path.join(instance_minecraft_dir(self.instance_name), "mods")
        self.installed_mods = set()
        if os.path.exists(mods_dir):
            for f in os.listdir(mods_dir):
                if f.endswith(".jar"):
                    self.installed_mods.add(f.lower())
        self.status_label.configure(
            text=f"Установлено модов: {len(self.installed_mods)}",
            text_color="#4CAF50")

    def load_popular(self):
        """Загружает популярные моды при открытии"""
        self.search_entry.delete(0, "end")
        self.do_search(query="")

    def search(self):
        query = self.search_entry.get().strip()
        self.do_search(query=query)

    def do_search(self, query=""):
        # Определяем категорию
        cat_label = self.category_var.get()
        category = CATEGORY_LABELS_REVERSE.get(cat_label, "Все категории")

        # Определяем сортировку
        sort_label = self.sort_var.get()
        sort_map = {
            "📥 По популярности": "downloads",
            "🆕 Новые": "newest",
            "🔥 Обновлённые": "updated",
            "🎯 По релевантности": "relevance",
        }
        index = sort_map.get(sort_label, "downloads")

        # UI
        self.search_btn.configure(state="disabled", text="Поиск...")
        info = f"«{query}»" if query else "популярные"
        if category != "Все категории":
            info += f" · {CATEGORY_LABELS.get(category, category)}"
        self.status_label.configure(text=f"Загрузка {info}...", text_color="#f39c12")

        # Очистка
        for w in self.scroll.winfo_children():
            w.destroy()
        self._icon_refs.clear()

        def do():
            results = search_modrinth_mods_advanced(
                query=query,
                mc_version=self.mc_version,
                category=category,
                limit=20,
                index=index
            )
            self.after(0, lambda r=results: self.render_results(r, query, category))

        threading.Thread(target=do, daemon=True).start()

    def render_results(self, results, query, category):
        self.search_btn.configure(state="normal", text="Найти")

        if not results:
            info = f"«{query}»" if query else "популярные моды"
            if category != "Все категории":
                info += f" в категории {CATEGORY_LABELS.get(category, category)}"
            self.status_label.configure(text=f"Ничего не найдено: {info}",
                                         text_color="#e74c3c")
            ctk.CTkLabel(self.scroll,
                         text=f"🔍 Ничего не найдено\n\n{info}\n\n"
                              f"Попробуй другую категорию или версию MC",
                         font=("Arial", 12), text_color="gray",
                         justify="center").pack(pady=50)
            return

        info = f"«{query}»" if query else "популярные"
        if category != "Все категории":
            info += f" · {CATEGORY_LABELS.get(category, category)}"
        self.status_label.configure(
            text=f"Найдено: {len(results)} модов ({info})",
            text_color="#4CAF50")

        for mod in results:
            self.create_mod_card(mod)

    def create_mod_card(self, mod):
        card = ctk.CTkFrame(self.scroll, fg_color=("gray80", "gray20"),
                            corner_radius=10)
        card.pack(fill="x", padx=5, pady=5)

        top_row = ctk.CTkFrame(card, fg_color="transparent")
        top_row.pack(fill="x", padx=12, pady=(10, 3))

        icon_label = ctk.CTkLabel(
            top_row, text="🧩", width=64, height=64,
            fg_color=("gray70", "gray25"), corner_radius=8,
            font=("Arial", 28), text_color="gray")
        icon_label.pack(side="left", padx=(0, 12))

        icon_url = mod.get("icon_url")
        if icon_url:
            def load_icon(url=icon_url, lbl=icon_label):
                img = download_mod_icon(url)
                if img:
                    self.after(0, lambda: self._apply_icon(lbl, img))
            threading.Thread(target=load_icon, daemon=True).start()

        info_col = ctk.CTkFrame(top_row, fg_color="transparent")
        info_col.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(info_col, text=mod.get("title", "Unknown"),
                     font=("Arial", 14, "bold"),
                     text_color="#4CAF50", anchor="w").pack(fill="x")

        meta = ctk.CTkFrame(info_col, fg_color="transparent")
        meta.pack(fill="x", pady=(2, 3))

        ctk.CTkLabel(meta, text=f"👤 {mod.get('author', '?')}",
                     font=("Arial", 10),
                     text_color="gray").pack(side="left", padx=(0, 10))

        downloads = mod.get("downloads", 0)
        if downloads >= 1_000_000:
            dl_text = f"📥 {downloads / 1_000_000:.1f}M"
        elif downloads >= 1000:
            dl_text = f"📥 {downloads / 1000:.0f}K"
        else:
            dl_text = f"📥 {downloads}"

        ctk.CTkLabel(meta, text=dl_text, font=("Arial", 10),
                     text_color="gray").pack(side="left", padx=(0, 10))

        loaders = mod.get("categories", []) + mod.get("loaders", [])
        loaders_text = ", ".join([l for l in loaders
                                   if l in ["forge", "fabric", "quilt", "neoforge"]])
        if loaders_text:
            ctk.CTkLabel(meta, text=f"⚙ {loaders_text}",
                         font=("Arial", 10),
                         text_color="gray").pack(side="left")

        # Категории
        cats = mod.get("categories", [])
        interesting_cats = [c for c in cats if c in MODRINTH_CATEGORIES]
        if interesting_cats:
            cat_text = " · ".join([CATEGORY_LABELS.get(c, c) for c in interesting_cats[:3]])
            ctk.CTkLabel(info_col, text=cat_text,
                         font=("Arial", 10),
                         text_color="#9b59b6",
                         anchor="w").pack(fill="x", pady=(0, 3))

        desc = mod.get("description", "Без описания")
        if len(desc) > 180:
            desc = desc[:177] + "..."
        ctk.CTkLabel(info_col, text=desc,
                     font=("Arial", 10), anchor="w", justify="left",
                     wraplength=460,
                     text_color=("black", "#d4d4d4")).pack(fill="x", pady=(0, 3))

        project_id = mod.get("project_id") or mod.get("slug")
        mod_slug = mod.get("slug", "mod")

        install_btn = ctk.CTkButton(
            info_col, text="📥 Установить", width=130, height=28,
            font=("Arial", 11, "bold"),
            fg_color="#4CAF50", hover_color="#3d8b40",
            command=lambda: self.install_mod(project_id, mod_slug, install_btn))
        install_btn.pack(anchor="e", pady=(3, 0))

    def _apply_icon(self, label, pil_image):
        try:
            w, h = pil_image.size
            size = min(w, h)
            left = (w - size) // 2
            top = (h - size) // 2
            cropped = pil_image.crop((left, top, left + size, top + size))
            cropped = cropped.resize((64, 64), Image.LANCZOS)
            ctk_img = ctk.CTkImage(light_image=cropped, dark_image=cropped,
                                    size=(64, 64))
            label.configure(image=ctk_img, text="")
            self._icon_refs.append(ctk_img)
        except Exception as e:
            log(f"apply_icon error: {e}", "WARN")

    def install_mod(self, project_id, mod_slug, btn):
        btn.configure(state="disabled", text="⏳ Проверка...")
        self.status_label.configure(text=f"Проверка зависимостей {mod_slug}...",
                                     text_color="#f39c12")

        def do_install():
            deps = get_mod_dependencies(project_id, self.mc_version)
            if deps:
                log(f"{mod_slug} requires: {len(deps)} deps")

            self.after(0, lambda: btn.configure(text="⏳ Скачивание..."))
            self.after(0, lambda: self.status_label.configure(
                text=f"Скачивание {mod_slug} + {len(deps)} зависимостей...",
                text_color="#f39c12"))

            success, info = install_mod_from_modrinth(
                self.instance_name, project_id, self.mc_version)

            self.after(0, lambda: self.on_install_done(success, info, btn, deps))

        threading.Thread(target=do_install, daemon=True).start()

    def on_install_done(self, success, info, btn, deps=None):
        if success:
            btn.configure(text="✓ Установлен", fg_color="#2d5a2d",
                          state="disabled")
            if deps:
                dep_text = f" + {len(deps)} зависимостей"
            else:
                dep_text = ""
            self.status_label.configure(text=f"✓ {info}{dep_text}",
                                         text_color="#4CAF50")
            self.refresh_installed()
        else:
            btn.configure(text="❌ Ошибка", fg_color="#5a2a2a", state="normal")
            self.status_label.configure(text=f"❌ {info[:80]}",
                                         text_color="#e74c3c")


# ============ СЕТЕВАЯ ИГРА ============
class NetworkWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Сетевая игра")
        self.geometry("560x680")
        self.resizable(False, False)
        self.grab_set()
        self.after(100, self.lift)
        set_icon(self)
        self.my_ip = None
        self.my_vpn = None

        ctk.CTkLabel(self, text="🌐  Сетевая игра",
                     font=("Arial", 22, "bold"),
                     text_color="#4CAF50").pack(pady=(20, 3))
        ctk.CTkLabel(self, text="Играй с друзьями через Radmin VPN / Hamachi",
                     font=("Arial", 11), text_color="gray").pack(pady=(0, 15))

        my_ip_section = ctk.CTkFrame(self, fg_color=("gray85", "gray20"),
                                      corner_radius=10)
        my_ip_section.pack(fill="x", padx=25, pady=(0, 12))
        ctk.CTkLabel(my_ip_section, text="📡 Твой IP",
                     font=("Arial", 14, "bold"),
                     text_color="#4CAF50").pack(pady=(12, 5))
        self.ip_label = ctk.CTkLabel(my_ip_section, text="⏳ Определение...",
                                      font=("Consolas", 18, "bold"),
                                      text_color="#f39c12")
        self.ip_label.pack(pady=(0, 5))
        self.vpn_label = ctk.CTkLabel(my_ip_section, text="",
                                       font=("Arial", 11), text_color="gray")
        self.vpn_label.pack(pady=(0, 8))
        ip_btns = ctk.CTkFrame(my_ip_section, fg_color="transparent")
        ip_btns.pack(pady=(0, 12))
        ctk.CTkButton(ip_btns, text="🔄 Обновить", width=130, height=32,
                      font=("Arial", 11), fg_color="#4CAF50", hover_color="#3d8b40",
                      command=self.refresh_ip).pack(side="left", padx=3)
        ctk.CTkButton(ip_btns, text="📋 Копировать", width=130, height=32,
                      font=("Arial", 11), fg_color="#555", hover_color="#333",
                      command=self.copy_ip).pack(side="left", padx=3)

        connect_section = ctk.CTkFrame(self, fg_color=("gray85", "gray20"),
                                        corner_radius=10)
        connect_section.pack(fill="x", padx=25, pady=(0, 12))
        ctk.CTkLabel(connect_section, text="🔗 Подключиться к другу",
                     font=("Arial", 14, "bold"),
                     text_color="#4CAF50").pack(pady=(12, 5))
        ctk.CTkLabel(connect_section, text="Введи IP друга:",
                     font=("Arial", 11), text_color="gray").pack(pady=(0, 5))
        ip_input_frame = ctk.CTkFrame(connect_section, fg_color="transparent")
        ip_input_frame.pack(fill="x", padx=15, pady=(0, 8))
        self.friend_ip_entry = ctk.CTkEntry(ip_input_frame, height=35,
                                             font=("Consolas", 13),
                                             placeholder_text="25.12.34.56")
        self.friend_ip_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        saved_ip = self.parent.config_data.get("last_server_ip", "")
        if saved_ip:
            self.friend_ip_entry.insert(0, saved_ip)
        ctk.CTkButton(ip_input_frame, text="📋", width=45, height=35,
                      font=("Arial", 14), fg_color="#555", hover_color="#333",
                      command=self.paste_ip).pack(side="left")
        ctk.CTkLabel(connect_section, text="Порт (по умолчанию 25565):",
                     font=("Arial", 11), text_color="gray").pack(pady=(5, 5))
        self.friend_port_entry = ctk.CTkEntry(connect_section, height=32,
                                               font=("Consolas", 12),
                                               placeholder_text="25565")
        self.friend_port_entry.insert(0, "25565")
        self.friend_port_entry.pack(fill="x", padx=15, pady=(0, 8))
        ctk.CTkButton(connect_section, text="🎮 Подключиться и играть",
                      height=40, font=("Arial", 13, "bold"),
                      fg_color="#4CAF50", hover_color="#3d8b40",
                      command=self.connect_to_friend).pack(fill="x", padx=15, pady=(5, 12))

        info_scroll = ctk.CTkScrollableFrame(self, fg_color=("gray90", "gray15"),
                                              width=510, height=200)
        info_scroll.pack(padx=25, pady=(0, 15), fill="both", expand=True)

        instructions = [
            ("📖 Как играть с друзьями", "bold"),
            ("", "normal"),
            ("1️⃣ Все устанавливают Radmin VPN или Hamachi", "normal"),
            ("   • Radmin VPN: https://www.radmin-vpn.com/", "gray"),
            ("   • Hamachi: https://vpn.net/", "gray"),
            ("", "normal"),
            ("2️⃣ Создайте общую сеть (имя + пароль)", "normal"),
            ("", "normal"),
            ("3️⃣ Проверьте IP в окне сверху", "normal"),
            ("", "normal"),
            ("4️⃣ Хост: Esc → «Открыть для сети»", "normal"),
            ("   • Запомните порт (например, 54321)", "gray"),
            ("   • Скопируйте свой IP кнопкой 📋", "gray"),
            ("", "normal"),
            ("5️⃣ Друзья вводят IP и порт → Подключиться", "normal"),
            ("", "normal"),
            ("⚠️ Все должны быть в одной сети VPN!", "warn"),
        ]

        for text, style in instructions:
            if style == "bold":
                ctk.CTkLabel(info_scroll, text=text, font=("Arial", 12, "bold"),
                             text_color="#4CAF50", anchor="w",
                             justify="left").pack(fill="x", padx=5, pady=(8, 2))
            elif style == "warn":
                ctk.CTkLabel(info_scroll, text=text, font=("Arial", 10),
                             text_color="#f39c12", anchor="w",
                             justify="left").pack(fill="x", padx=10, pady=1)
            elif style == "gray":
                ctk.CTkLabel(info_scroll, text=text, font=("Arial", 10),
                             text_color="gray", anchor="w",
                             justify="left").pack(fill="x", padx=10, pady=1)
            elif text == "":
                ctk.CTkLabel(info_scroll, text="", font=("Arial", 5)).pack(pady=2)
            else:
                ctk.CTkLabel(info_scroll, text=text, font=("Arial", 11),
                             anchor="w", justify="left").pack(fill="x", padx=5, pady=1)

        ctk.CTkButton(self, text="Закрыть", width=200, height=38,
                      font=("Arial", 12), fg_color="#555", hover_color="#333",
                      command=self.destroy).pack(pady=(0, 15))

        self.after(200, self.refresh_ip)

    def refresh_ip(self):
        self.ip_label.configure(text="⏳ Сканирую...", text_color="#f39c12")
        self.vpn_label.configure(text="")
        self.update()

        def scan():
            ip, vpn = get_vpn_ip()
            self.after(0, lambda: self.apply_ip(ip, vpn))

        threading.Thread(target=scan, daemon=True).start()

    def apply_ip(self, ip, vpn):
        self.my_ip = ip
        self.my_vpn = vpn
        if ip:
            self.ip_label.configure(text=ip, text_color="#4CAF50")
            self.vpn_label.configure(text=f"✓ {vpn}", text_color="#4CAF50")
        else:
            self.ip_label.configure(text="❌ Не найден", text_color="#e74c3c")
            self.vpn_label.configure(text="Radmin VPN / Hamachi не запущен",
                                      text_color="#e74c3c")

    def copy_ip(self):
        if self.my_ip:
            self.clipboard_clear()
            self.clipboard_append(self.my_ip)
            self.parent.set_status(f"IP скопирован: {self.my_ip}", "#4CAF50")

    def paste_ip(self):
        try:
            text = self.clipboard_get()
            self.friend_ip_entry.delete(0, "end")
            self.friend_ip_entry.insert(0, text.strip())
        except Exception:
            pass

    def connect_to_friend(self):
        ip = self.friend_ip_entry.get().strip()
        port = self.friend_port_entry.get().strip() or "25565"
        if not ip:
            self.parent.set_status("Введи IP друга", "#e74c3c")
            return
        if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', ip):
            self.parent.set_status("Неверный формат IP", "#e74c3c")
            return
        try:
            pn = int(port)
            if pn < 1 or pn > 65535:
                raise ValueError
        except ValueError:
            self.parent.set_status("Неверный порт", "#e74c3c")
            return
        self.parent.config_data["last_server_ip"] = ip
        save_config(self.parent.config_data)
        self.parent.set_status(f"Подключение к {ip}:{port}...", "#4CAF50")
        self.parent.open_quick_connect(ip, port)
        self.destroy()


# ============ КОНСОЛЬ ============
class ConsoleWindow(ctk.CTkToplevel):
    def __init__(self, parent, instance_name):
        super().__init__(parent)
        self.title(f"Консоль — {instance_name}")
        self.geometry("900x600")
        self.minsize(700, 400)
        set_icon(self)
        self.log_lines = []
        self.process = None
        self.instance_name = instance_name

        header = ctk.CTkFrame(self, height=50, corner_radius=0)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)
        ctk.CTkLabel(header, text=f"🖥  Консоль · {instance_name}",
                     font=("Consolas", 14, "bold"),
                     text_color="#4CAF50").pack(side="left", padx=15)
        self.status_label = ctk.CTkLabel(header, text="● Запуск...",
                                          font=("Arial", 12),
                                          text_color="#f39c12")
        self.status_label.pack(side="right", padx=15)

        btn_bar = ctk.CTkFrame(self, height=40, corner_radius=0,
                               fg_color=("gray85", "gray20"))
        btn_bar.pack(fill="x", side="top")
        btn_bar.pack_propagate(False)
        ctk.CTkButton(btn_bar, text="🗑 Очистить", width=110, height=30,
                      font=("Arial", 11), fg_color="#555", hover_color="#333",
                      command=self.clear_log).pack(side="left", padx=4, pady=5)
        ctk.CTkButton(btn_bar, text="💾 Сохранить", width=120, height=30,
                      font=("Arial", 11), fg_color="#555", hover_color="#333",
                      command=self.save_to_file).pack(side="left", padx=4, pady=5)
        ctk.CTkButton(btn_bar, text="📋 Копировать", width=120, height=30,
                      font=("Arial", 11), fg_color="#555", hover_color="#333",
                      command=self.copy_all).pack(side="left", padx=4, pady=5)
        ctk.CTkButton(btn_bar, text="📂 Папка экземпляра", width=160, height=30,
                      font=("Arial", 11), fg_color="#3a3a3a", hover_color="#4a4a4a",
                      command=self.open_instance_folder).pack(side="left", padx=4, pady=5)
        ctk.CTkButton(btn_bar, text="📦 Папка модов", width=140, height=30,
                      font=("Arial", 11), fg_color="#3a3a3a", hover_color="#4a4a4a",
                      command=self.open_mods_folder).pack(side="left", padx=4, pady=5)
        self.autoscroll_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(btn_bar, text="Автопрокрутка",
                        variable=self.autoscroll_var, font=("Arial", 11),
                        checkbox_width=18,
                        checkbox_height=18).pack(side="right", padx=15, pady=5)

        self.textbox = ctk.CTkTextbox(self, font=("Consolas", 11),
                                       fg_color=("#1e1e1e", "#0d0d0d"),
                                       text_color="#d4d4d4", wrap="word")
        self.textbox.pack(fill="both", expand=True, padx=10, pady=(10, 10))
        for tag, color in [("error", "#e74c3c"), ("warn", "#f39c12"),
                           ("info", "#4CAF50"), ("normal", "#d4d4d4"),
                           ("system", "#3498db")]:
            self.textbox.tag_config(tag, foreground=color)

        footer = ctk.CTkFrame(self, height=40, corner_radius=0,
                              fg_color=("gray85", "gray20"))
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)
        self.stats_label = ctk.CTkLabel(footer, text="Строк: 0",
                                         font=("Arial", 11), text_color="gray")
        self.stats_label.pack(side="left", padx=15, pady=5)
        ctk.CTkButton(footer, text="❌ Стоп", width=120, height=30,
                      font=("Arial", 11), fg_color="#5a2a2a", hover_color="#7a2020",
                      command=self.kill_process).pack(side="right", padx=5, pady=5)

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def append_log(self, line, level="normal"):
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        self.log_lines.append(line)
        try:
            self.textbox.insert("end", line + "\n", level)
            if self.autoscroll_var.get():
                self.textbox.see("end")
            self.stats_label.configure(text=f"Строк: {len(self.log_lines)}")
        except Exception:
            pass

    def add_message(self, text, level="info"):
        prefixes = {"info": "ℹ ", "error": "✗ ", "warn": "⚠ ",
                    "ok": "✓ ", "system": "» "}
        prefix = prefixes.get(level, "")
        tag = level if level in ("error", "warn", "info") else (
            "system" if level == "system" else "normal")
        if level == "ok":
            tag = "info"
        self.append_log(f"{prefix}{text}", tag)

    def update_status(self, text, color="#f39c12"):
        try:
            if self.winfo_exists():
                self.status_label.configure(text=text, text_color=color)
        except Exception:
            pass

    def clear_log(self):
        self.textbox.delete("1.0", "end")
        self.log_lines.clear()
        self.stats_label.configure(text="Строк: 0")

    def save_to_file(self):
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(
            defaultextension=".log",
            filetypes=[("Log files", "*.log"), ("All files", "*.*")],
            initialfile="minecraft_log.txt")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(self.log_lines))
            self.add_message(f"Лог сохранён: {path}", "ok")

    def copy_all(self):
        self.clipboard_clear()
        self.clipboard_append("\n".join(self.log_lines))
        self.add_message("Лог скопирован", "ok")

    def open_instance_folder(self):
        mc_dir = instance_minecraft_dir(self.instance_name)
        if os.path.exists(mc_dir):
            os.startfile(mc_dir)

    def open_mods_folder(self):
        mods_path = os.path.join(instance_minecraft_dir(self.instance_name), "mods")
        os.makedirs(mods_path, exist_ok=True)
        os.startfile(mods_path)

    def kill_process(self):
        if self.process and self.process.poll() is None:
            try:
                self.process.kill()
                self.add_message("Процесс убит", "warn")
                self.update_status("● Остановлено", "#e74c3c")
            except Exception as e:
                self.add_message(f"Ошибка: {e}", "error")

    def on_close(self):
        if self.process and self.process.poll() is None:
            result = messagebox.askyesno("Игра запущена",
                                          "Minecraft работает. Закрыть консоль?")
            if not result:
                return
        self.destroy()


# ============ ELY AUTH ============
class ElyAuthWindow(ctk.CTkToplevel):
    def __init__(self, parent, on_success):
        super().__init__(parent)
        self.title("Вход в Ely.by")
        self.geometry("440x500")
        self.resizable(False, False)
        self.grab_set()
        self.after(100, self.lift)
        set_icon(self)
        self.on_success = on_success
        self.twofa_needed = False

        ctk.CTkLabel(self, text="🔐 Вход в Ely.by",
                     font=("Arial", 22, "bold"),
                     text_color="#4CAF50").pack(pady=(25, 5))
        ctk.CTkLabel(self, text="Введите данные аккаунта Ely.by",
                     font=("Arial", 11), text_color="gray").pack(pady=(0, 25))

        ctk.CTkLabel(self, text="Логин (или E-mail):",
                     font=("Arial", 12), anchor="w").pack(fill="x", padx=40)
        self.login_entry = ctk.CTkEntry(self, width=360, height=35,
                                         font=("Arial", 13))
        self.login_entry.pack(pady=(5, 15))

        ctk.CTkLabel(self, text="Пароль:",
                     font=("Arial", 12), anchor="w").pack(fill="x", padx=40)
        self.pass_entry = ctk.CTkEntry(self, width=360, height=35,
                                        font=("Arial", 13), show="●")
        self.pass_entry.pack(pady=(5, 15))

        self.twofa_frame = ctk.CTkFrame(self, fg_color="transparent")
        ctk.CTkLabel(self.twofa_frame, text="Код 2FA (из приложения):",
                     font=("Arial", 12), anchor="w").pack(fill="x")
        self.twofa_entry = ctk.CTkEntry(self.twofa_frame, width=360, height=35,
                                         font=("Consolas", 14),
                                         placeholder_text="123456")
        self.twofa_entry.pack(pady=(5, 5))

        self.error_label = ctk.CTkLabel(self, text="", text_color="#e74c3c",
                                         font=("Arial", 11), wraplength=360)
        self.error_label.pack(pady=(0, 10))

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=(5, 10))
        self.login_btn = ctk.CTkButton(btn_frame, text="Войти",
                                        width=170, height=40,
                                        font=("Arial", 13, "bold"),
                                        fg_color="#4CAF50", hover_color="#3d8b40",
                                        command=self.do_login)
        self.login_btn.pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="Отмена", width=170, height=40,
                      font=("Arial", 13), fg_color="#555", hover_color="#333",
                      command=self.destroy).pack(side="left", padx=5)

        ctk.CTkLabel(self,
                     text="⚠ Сессия только пока лаунчер открыт",
                     font=("Arial", 10), text_color="#f39c12").pack(pady=(10, 0))

    def do_login(self):
        login = self.login_entry.get().strip()
        password = self.pass_entry.get()
        twofa = self.twofa_entry.get().strip() if self.twofa_needed else ""

        if not login or not password:
            self.error_label.configure(text="Заполни логин и пароль!")
            return
        if self.twofa_needed and not twofa:
            self.error_label.configure(text="Введи код 2FA!")
            return

        self.login_btn.configure(state="disabled", text="Вход...")
        self.error_label.configure(text="")

        def auth_thread():
            try:
                result = ely_authenticate(login, password, twofa)
                self.after(0, lambda r=result: self.handle_result(r))
            except Exception as e:
                self.after(0, lambda: self.error_label.configure(
                    text=f"Ошибка: {str(e)[:60]}"))

        threading.Thread(target=auth_thread, daemon=True).start()

    def handle_result(self, result):
        if result == "NEED_2FA":
            self.twofa_needed = True
            self.twofa_frame.pack(fill="x", padx=40, pady=(0, 15), before=self.error_label)
            self.error_label.configure(
                text="⚠ Включена 2FA. Введи код из приложения.",
                text_color="#f39c12"
            )
            self.login_btn.configure(state="normal", text="Войти")
            return

        if result and isinstance(result, dict):
            self.on_success(result)
            self.destroy()
        else:
            self.error_label.configure(text="Неверный логин, пароль или код 2FA.")
            self.login_btn.configure(state="normal", text="Войти")




# ============ ВЫБОР ВЕРСИИ ============
class VersionSelectWindow(ctk.CTkToplevel):
    def __init__(self, parent, vanilla_versions, current_version, on_selected):
        super().__init__(parent)
        self.title("Выбор версии")
        self.geometry("540x640")
        self.resizable(False, False)
        self.grab_set()
        self.after(100, self.lift)
        set_icon(self)
        self.vanilla_versions = vanilla_versions
        self.selected = current_version
        self.on_selected = on_selected

        ctk.CTkLabel(self, text="📋 Выбор версии Minecraft",
                     font=("Arial", 20, "bold"),
                     text_color="#4CAF50").pack(pady=(20, 15))

        sf = ctk.CTkFrame(self, fg_color="transparent")
        sf.pack(fill="x", padx=30, pady=(0, 10))
        ctk.CTkLabel(sf, text="🔍", font=("Arial", 16)).pack(side="left", padx=(0, 5))
        self.search_entry = ctk.CTkEntry(sf, height=35, font=("Arial", 13),
                                          placeholder_text="Поиск: например 1.16")
        self.search_entry.pack(side="left", fill="x", expand=True)
        self.search_entry.bind("<KeyRelease>", lambda e: self.render_list())

        qf = ctk.CTkFrame(self, fg_color="transparent")
        qf.pack(fill="x", padx=30, pady=(0, 10))
        for v in ["Последняя", "1.20.1", "1.16.5", "1.12.2", "1.7.10"]:
            ctk.CTkButton(qf, text=v, width=88, height=30, font=("Arial", 11),
                          fg_color="#3a3a3a", hover_color="#4a4a4a",
                          command=lambda ver=v: self.quick_select(ver)).pack(side="left", padx=2)

        self.scroll = ctk.CTkScrollableFrame(self, width=460, height=380,
                                              fg_color=("gray90", "gray15"))
        self.scroll.pack(padx=30, pady=(0, 10), fill="both", expand=True)

        self.info_label = ctk.CTkLabel(self, text=f"Выбрано: {self.selected}",
                                        font=("Arial", 13, "bold"),
                                        text_color="#4CAF50")
        self.info_label.pack(pady=(0, 10))

        bf = ctk.CTkFrame(self, fg_color="transparent")
        bf.pack(pady=(0, 20))
        ctk.CTkButton(bf, text="✓ Выбрать", width=150, height=40,
                      font=("Arial", 13, "bold"), fg_color="#4CAF50",
                      hover_color="#3d8b40", command=self.confirm).pack(side="left", padx=5)
        ctk.CTkButton(bf, text="Отмена", width=150, height=40,
                      font=("Arial", 13), fg_color="#555", hover_color="#333",
                      command=self.destroy).pack(side="left", padx=5)

        self.render_list()

    def render_list(self):
        for w in self.scroll.winfo_children():
            w.destroy()
        query = self.search_entry.get().strip().lower()
        versions = [v for v in self.vanilla_versions if query in v.lower()] if query else self.vanilla_versions
        if not versions:
            ctk.CTkLabel(self.scroll, text="Ничего не найдено 🔍",
                          font=("Arial", 12), text_color="gray").pack(pady=20)
            return
        for v in versions:
            ctk.CTkButton(self.scroll, text=v, width=420, height=32,
                          font=("Arial", 12), anchor="w",
                          fg_color="#4CAF50" if v == self.selected else "#2b2b2b",
                          hover_color="#3d8b40",
                          command=lambda ver=v: self.select_version(ver)).pack(pady=2, padx=5, fill="x")

    def quick_select(self, v):
        if v == "Последняя":
            if self.vanilla_versions:
                self.selected = self.vanilla_versions[0]
        elif v in self.vanilla_versions:
            self.selected = v
        else:
            return
        self.info_label.configure(text=f"Выбрано: {self.selected}")
        self.render_list()

    def select_version(self, v):
        self.selected = v
        self.info_label.configure(text=f"Выбрано: {v}")
        self.render_list()

    def confirm(self):
        self.on_selected(self.selected)
        self.destroy()


# ============ СОЗДАНИЕ ЭКЗЕМПЛЯРА ============
class CreateInstanceWindow(ctk.CTkToplevel):
    def __init__(self, parent, all_versions, on_created):
        super().__init__(parent)
        self.title("Создать экземпляр")
        self.geometry("440x620")
        self.resizable(False, False)
        self.on_created = on_created
        self.all_versions = all_versions
        self.grab_set()
        self.after(100, self.lift)
        set_icon(self)

        ctk.CTkLabel(self, text="➕ Новый экземпляр",
                     font=("Arial", 20, "bold"),
                     text_color="#4CAF50").pack(pady=(20, 15))

        ctk.CTkLabel(self, text="Название:", font=("Arial", 12),
                     anchor="w").pack(fill="x", padx=40)
        self.name_entry = ctk.CTkEntry(self, width=360, height=35,
                                        placeholder_text="Например: Моя выживалка")
        self.name_entry.pack(pady=(5, 12))

        ctk.CTkLabel(self, text="Версия Minecraft:",
                     font=("Arial", 12), anchor="w").pack(fill="x", padx=40)
        self.selected_version = all_versions[0] if all_versions else "1.20.1"
        vf = ctk.CTkFrame(self, fg_color="transparent")
        vf.pack(fill="x", padx=40, pady=(5, 12))
        self.version_btn = ctk.CTkButton(vf, text=f"📋 {self.selected_version}",
                                          width=250, height=35, font=("Arial", 12),
                                          fg_color="#2b2b2b", hover_color="#3a3a3a",
                                          command=self.open_version_select)
        self.version_btn.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(vf, text="🔍", width=50, height=35, font=("Arial", 14),
                      fg_color="#4CAF50", hover_color="#3d8b40",
                      command=self.open_version_select).pack(side="left", padx=(5, 0))

        ctk.CTkLabel(self, text="Загрузчик модов:",
                     font=("Arial", 12), anchor="w").pack(fill="x", padx=40)
        self.loader_var = ctk.StringVar(value="Vanilla (без модов)")
        ctk.CTkOptionMenu(
            self, variable=self.loader_var, width=360, height=35,
            font=("Arial", 12),
            values=["Vanilla (без модов)", "Forge", "Fabric"]
        ).pack(pady=(5, 12))

        ctk.CTkLabel(self, text="Оперативная память (МБ):",
                     font=("Arial", 12), anchor="w").pack(fill="x", padx=40)
        rf = ctk.CTkFrame(self, fg_color="transparent")
        rf.pack(fill="x", padx=40, pady=(5, 0))
        steps = max(1, (RAM_MAX - RAM_MIN) // 256)
        self.ram_slider = ctk.CTkSlider(rf, from_=RAM_MIN, to=RAM_MAX,
                                         number_of_steps=steps,
                                         command=self.on_ram_change)
        default_ram = max(2048, (RAM_MAX // 2 // 256) * 256)
        self.ram_slider.set(default_ram)
        self.ram_slider.pack(side="left", fill="x", expand=True)
        self.ram_label = ctk.CTkLabel(rf, text=str(default_ram),
                                       font=("Arial", 12, "bold"),
                                       text_color="#4CAF50", width=60)
        self.ram_label.pack(side="left", padx=(10, 0))
        ctk.CTkLabel(self, text=f"💡 Доступно: до {RAM_MAX} МБ",
                     font=("Arial", 10), text_color="gray").pack(pady=(3, 12))

        bf = ctk.CTkFrame(self, fg_color="transparent")
        bf.pack(pady=(5, 15))
        ctk.CTkButton(bf, text="Создать", width=150, height=40,
                      fg_color="#4CAF50", hover_color="#3d8b40",
                      command=self.create).pack(side="left", padx=5)
        ctk.CTkButton(bf, text="Отмена", width=150, height=40,
                      fg_color="#555", hover_color="#333",
                      command=self.destroy).pack(side="left", padx=5)
        self.error_label = ctk.CTkLabel(self, text="", text_color="#e74c3c",
                                         font=("Arial", 11))
        self.error_label.pack()

    def open_version_select(self):
        VersionSelectWindow(self, self.all_versions, self.selected_version,
                             self.on_version_selected)

    def on_version_selected(self, v):
        self.selected_version = v
        self.version_btn.configure(text=f"📋 {v}")

    def on_ram_change(self, value):
        val = int(value // 256 * 256)
        self.ram_slider.set(val)
        self.ram_label.configure(text=str(val))

    def create(self):
        name = self.name_entry.get().strip()
        version = self.selected_version
        ram = int(self.ram_slider.get())
        loader_display = self.loader_var.get()
        loader_map = {
            "Vanilla (без модов)": "vanilla",
            "Forge": "forge",
            "Fabric": "fabric"
        }
        mod_loader = loader_map.get(loader_display, "vanilla")

        if not name:
            self.error_label.configure(text="Введи название!")
            return
        if os.path.exists(instance_path(name)):
            self.error_label.configure(text="Уже существует!")
            return
        bad = ['\\', '/', ':', '*', '?', '"', '<', '>', '|']
        if any(c in name for c in bad):
            self.error_label.configure(text="Недопустимые символы!")
            return

        create_instance(name, version, ram, mod_loader)
        self.on_created()
        self.destroy()


# ============ РЕДАКТИРОВАНИЕ ЭКЗЕМПЛЯРА ============
class EditInstanceWindow(ctk.CTkToplevel):
    def __init__(self, parent, instance_name, on_saved):
        super().__init__(parent)
        self.parent = parent
        self.instance_name = instance_name
        self.on_saved = on_saved
        self.title("Настройки экземпляра")
        self.geometry("480x700")
        self.minsize(480, 550)
        self.resizable(False, True)
        self.grab_set()
        self.after(100, self.lift)
        set_icon(self)

        with open(instance_config_path(instance_name), "r", encoding="utf-8") as f:
            self.inst_data = json.load(f)
        self.inst_data.setdefault("ram", 2048)
        self.inst_data.setdefault("mod_loader", "vanilla")
        self.inst_data.setdefault("launch_version", self.inst_data.get("version", ""))

        ctk.CTkLabel(self, text=f"⚙ {instance_name}",
                     font=("Arial", 18, "bold"),
                     text_color="#4CAF50").pack(pady=(15, 3))
        ctk.CTkLabel(self, text=f"Версия: {self.inst_data['version']}",
                     font=("Arial", 11), text_color="gray").pack(pady=(0, 10))

        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent", width=440)
        scroll.pack(fill="both", expand=True, padx=15, pady=(0, 10))

        # RAM
        ctk.CTkLabel(scroll, text="Оперативная память (МБ):",
                     font=("Arial", 12), anchor="w").pack(fill="x", pady=(5, 3))
        rf = ctk.CTkFrame(scroll, fg_color="transparent")
        rf.pack(fill="x", pady=(0, 15))
        steps = max(1, (RAM_MAX - RAM_MIN) // 256)
        self.ram_slider = ctk.CTkSlider(rf, from_=RAM_MIN, to=RAM_MAX,
                                         number_of_steps=steps,
                                         command=self.on_ram_change)
        saved_ram = max(min(self.inst_data["ram"], RAM_MAX), RAM_MIN)
        self.ram_slider.set(saved_ram)
        self.ram_slider.pack(side="left", fill="x", expand=True)
        self.ram_label = ctk.CTkLabel(rf, text=str(saved_ram),
                                       font=("Arial", 12, "bold"),
                                       text_color="#4CAF50", width=60)
        self.ram_label.pack(side="left", padx=(10, 0))

        # Загрузчик
        ctk.CTkLabel(scroll, text="⚙ Загрузчик модов:",
                     font=("Arial", 13, "bold"),
                     anchor="w", text_color="#4CAF50").pack(fill="x", pady=(10, 5))

        current_loader = self.inst_data.get("mod_loader", "vanilla")
        loader_map = {"vanilla": "Vanilla (без модов)",
                      "forge": "Forge", "fabric": "Fabric"}
        self.loader_display = ctk.StringVar(
            value=loader_map.get(current_loader, "Vanilla (без модов)")
        )

        self.loader_menu = ctk.CTkOptionMenu(
            scroll, variable=self.loader_display, height=32,
            font=("Arial", 12),
            values=["Vanilla (без модов)", "Forge", "Fabric"],
            command=self.on_loader_change
        )
        self.loader_menu.pack(fill="x", pady=(0, 5))

        current_launch = self.inst_data.get("launch_version", "")
        current_loader_id = self.inst_data.get("mod_loader", "vanilla")

        if current_loader_id == "vanilla":
            loader_info = "Ванильный Minecraft (без модов)"
            loader_color = "gray"
        else:
            loader_info = f"Активен: {current_loader_id.upper()} · ID: {current_launch}"
            loader_color = "#4CAF50"

        self.loader_status = ctk.CTkLabel(
            scroll, text=loader_info,
            font=("Arial", 10), text_color=loader_color,
            wraplength=400, justify="left"
        )
        self.loader_status.pack(fill="x", pady=(0, 8))

        self.install_loader_btn = ctk.CTkButton(
            scroll, text="📥 Установить выбранный загрузчик",
            height=36, font=("Arial", 11),
            fg_color="#4CAF50", hover_color="#3d8b40",
            command=self.install_loader
        )
        self.install_loader_btn.pack(fill="x", pady=(0, 5))

        self.install_progress = ctk.CTkProgressBar(scroll, height=6)
        self.install_progress.set(0)
        self.install_progress.pack(fill="x", pady=(0, 5))

        self.install_status_label = ctk.CTkLabel(
            scroll, text="",
            font=("Arial", 10), text_color="gray",
            wraplength=400, justify="left"
        )
        self.install_status_label.pack(fill="x", pady=(0, 15))

        bf = ctk.CTkFrame(self, fg_color="transparent")
        bf.pack(side="bottom", pady=15, fill="x", padx=20)
        ctk.CTkButton(bf, text="💾 Сохранить", height=38,
                      font=("Arial", 12), fg_color="#4CAF50",
                      hover_color="#3d8b40",
                      command=self.save).pack(side="left", expand=True, fill="x", padx=(0, 5))
        ctk.CTkButton(bf, text="Закрыть", height=38,
                      font=("Arial", 12), fg_color="#555", hover_color="#333",
                      command=self.destroy).pack(side="left", expand=True, fill="x", padx=(5, 0))

    def on_ram_change(self, value):
        val = int(value // 256 * 256)
        self.ram_slider.set(val)
        self.ram_label.configure(text=str(val))

    def on_loader_change(self, choice):
        mapping = {
            "Vanilla (без модов)": "vanilla",
            "Forge": "forge",
            "Fabric": "fabric"
        }
        loader_id = mapping.get(choice, "vanilla")

        if loader_id == "forge":
            self.loader_status.configure(
                text="⚠ Forge: для MC 1.12.2 нужна Java 8, для 1.17+ — Java 17",
                text_color="#f39c12"
            )
        elif loader_id == "fabric":
            self.loader_status.configure(
                text="⚠ Fabric: нужна Java 17 (1.20.1) или Java 21 (1.21)",
                text_color="#f39c12"
            )
        else:
            self.loader_status.configure(
                text="Ванильный Minecraft (без модов)",
                text_color="gray"
            )

    def install_loader(self):
        display = self.loader_display.get()
        mapping = {
            "Vanilla (без модов)": "vanilla",
            "Forge": "forge",
            "Fabric": "fabric"
        }
        loader_id = mapping.get(display, "vanilla")

        if loader_id == "vanilla":
            self.install_status_label.configure(
                text="Vanilla не требует установки", text_color="gray"
            )
            return

        mc_version = self.inst_data.get("version", "1.20.1")

        self.install_loader_btn.configure(state="disabled", text="⏳ Установка...")
        self.install_status_label.configure(
            text="Начинаю установку...", text_color="#f39c12"
        )
        self.install_progress.set(0)

        def status_callback(msg):
            self.after(0, lambda: self.install_status_label.configure(
                text=msg[:100], text_color="#f39c12"
            ))

        def do_install():
            try:
                success, result = install_loader_to_instance(
                    self.instance_name, loader_id, mc_version,
                    status_callback=status_callback
                )
                if success:
                    self.inst_data["mod_loader"] = loader_id
                    self.inst_data["launch_version"] = result
                    save_instance_config(self.instance_name, self.inst_data)
                    self.after(0, lambda: self.install_status_label.configure(
                        text=f"✅ Установлено! ID: {result}",
                        text_color="#4CAF50"
                    ))
                    self.after(0, lambda: self.install_progress.set(1.0))
                    self.after(0, lambda: self.loader_status.configure(
                        text=f"Активен: {loader_id.upper()} · ID: {result}",
                        text_color="#4CAF50"
                    ))
                else:
                    self.after(0, lambda: self.install_status_label.configure(
                        text=f"⚠ {result}", text_color="#f39c12"
                    ))
                    self.after(0, lambda: self.install_progress.set(0))
            except Exception as e:
                log(f"install_loader error: {e}", "ERROR")
                self.after(0, lambda: self.install_status_label.configure(
                    text=f"❌ Ошибка: {str(e)[:80]}", text_color="#e74c3c"
                ))
            finally:
                self.after(0, lambda: self.install_loader_btn.configure(
                    state="normal", text="📥 Установить выбранный загрузчик"
                ))

        threading.Thread(target=do_install, daemon=True).start()

    def save(self):
        ram = int(self.ram_slider.get())
        self.inst_data["ram"] = ram
        save_instance_config(self.instance_name, self.inst_data)
        self.on_saved()
        self.destroy()


# ============ НАСТРОЙКИ ============
class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Настройки")
        self.geometry("460x660")
        self.minsize(460, 520)
        self.resizable(False, True)
        self.grab_set()
        self.after(100, self.lift)
        set_icon(self)

        ctk.CTkLabel(self, text="⚙  Настройки",
                     font=("Arial", 20, "bold"),
                     text_color="#4CAF50").pack(pady=(15, 3))
        ctk.CTkLabel(self, text="CraftLauncher Beta v0.99",
                     font=("Arial", 10), text_color="gray").pack(pady=(0, 10))

        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent", width=420)
        scroll.pack(fill="both", expand=True, padx=15, pady=(0, 10))

        s1 = ctk.CTkFrame(scroll, fg_color="transparent")
        s1.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(s1, text="👤 Профиль", font=("Arial", 13, "bold"),
                     anchor="w").pack(fill="x", pady=(0, 5))
        ctk.CTkLabel(s1, text="Никнейм офлайн режима:",
                     font=("Arial", 11), anchor="w").pack(fill="x")
        self.nick_entry = ctk.CTkEntry(s1, height=32, font=("Arial", 12))
        self.nick_entry.insert(0, self.parent.config_data.get("nickname", "Steve"))
        self.nick_entry.pack(fill="x", pady=(3, 0))

        s2 = ctk.CTkFrame(scroll, fg_color="transparent")
        s2.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(s2, text="🎨 Внешний вид", font=("Arial", 13, "bold"),
                     anchor="w").pack(fill="x", pady=(0, 5))
        ctk.CTkLabel(s2, text="Тема оформления:",
                     font=("Arial", 11), anchor="w").pack(fill="x")
        self.theme_menu = ctk.CTkOptionMenu(s2, height=32, font=("Arial", 12),
                                             values=["Тёмная", "Светлая", "Системная"],
                                             command=self.change_theme)
        current_theme = self.parent.config_data.get("appearance", "dark")
        theme_map = {"dark": "Тёмная", "light": "Светлая", "system": "Системная"}
        self.theme_menu.set(theme_map.get(current_theme, "Тёмная"))
        self.theme_menu.pack(fill="x", pady=(3, 0))

        ctk.CTkLabel(s2, text="Фоновое изображение:",
                     font=("Arial", 11), anchor="w").pack(fill="x", pady=(8, 3))
        bf = ctk.CTkFrame(s2, fg_color="transparent")
        bf.pack(fill="x", pady=(0, 3))
        ctk.CTkButton(bf, text="📷 Выбрать", width=130, height=30,
                      font=("Arial", 11), fg_color="#4CAF50", hover_color="#3d8b40",
                      command=self.choose_background).pack(side="left", padx=(0, 5))
        ctk.CTkButton(bf, text="🔄 Сбросить", width=130, height=30,
                      font=("Arial", 11), fg_color="#555", hover_color="#333",
                      command=self.reset_background).pack(side="left")

        sb = ctk.CTkFrame(scroll, fg_color="transparent")
        sb.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(sb, text="⚡ Поведение", font=("Arial", 13, "bold"),
                     anchor="w").pack(fill="x", pady=(0, 5))
        self.auto_launch_var = ctk.BooleanVar(
            value=self.parent.config_data.get("auto_launch_after_install", True))
        ctk.CTkCheckBox(sb, text="Авто-запуск игры после установки",
                        variable=self.auto_launch_var, font=("Arial", 11),
                        checkbox_width=20, checkbox_height=20,
                        command=self.toggle_auto_launch).pack(fill="x", pady=(3, 8), anchor="w")
        self.show_console_var = ctk.BooleanVar(
            value=self.parent.config_data.get("show_console", True))
        ctk.CTkCheckBox(sb, text="Показывать консоль при запуске",
                        variable=self.show_console_var, font=("Arial", 11),
                        checkbox_width=20, checkbox_height=20,
                        command=self.toggle_show_console).pack(fill="x", pady=(0, 3), anchor="w")

        ss = ctk.CTkFrame(scroll, fg_color="transparent")
        ss.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(ss, text="💻 Система", font=("Arial", 13, "bold"),
                     anchor="w").pack(fill="x", pady=(0, 5))
        ctk.CTkLabel(ss, text=f"Всего RAM: {RAM_TOTAL} МБ\n"
                              f"Максимум для Minecraft: {RAM_MAX} МБ\n\n"
                              f"⌨ F11 — на весь экран\n"
                              f"Esc — выйти из fullscreen",
                     font=("Arial", 11), text_color="#4CAF50",
                     justify="left").pack(fill="x")

        s3 = ctk.CTkFrame(scroll, fg_color="transparent")
        s3.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(s3, text="📁 Папки", font=("Arial", 13, "bold"),
                     anchor="w").pack(fill="x", pady=(0, 5))
        ctk.CTkButton(s3, text="📂 Открыть папку лаунчера", height=32,
                      font=("Arial", 11), fg_color="#4CAF50", hover_color="#3d8b40",
                      command=self.open_launcher_folder).pack(fill="x", pady=(0, 5))
        ctk.CTkButton(s3, text="📝 Открыть launcher.log", height=32,
                      font=("Arial", 11), fg_color="#555", hover_color="#333",
                      command=self.open_log_file).pack(fill="x", pady=(0, 5))
        ctk.CTkButton(s3, text="📂 Открыть папку экземпляров", height=32,
                      font=("Arial", 11), fg_color="#555", hover_color="#333",
                      command=self.open_instances_folder).pack(fill="x")

        bf2 = ctk.CTkFrame(self, fg_color="transparent")
        bf2.pack(side="bottom", pady=15, fill="x", padx=20)
        ctk.CTkButton(bf2, text="💾 Сохранить", height=38,
                      font=("Arial", 12), fg_color="#4CAF50", hover_color="#3d8b40",
                      command=self.save_and_close).pack(side="left", expand=True,
                                                          fill="x", padx=(0, 5))
        ctk.CTkButton(bf2, text="Закрыть", height=38,
                      font=("Arial", 12), fg_color="#555", hover_color="#333",
                      command=self.destroy).pack(side="left", expand=True,
                                                   fill="x", padx=(5, 0))

    def toggle_auto_launch(self):
        self.parent.config_data["auto_launch_after_install"] = self.auto_launch_var.get()
        save_config(self.parent.config_data)

    def toggle_show_console(self):
        self.parent.config_data["show_console"] = self.show_console_var.get()
        save_config(self.parent.config_data)

    def change_theme(self, choice):
        mapping = {"Тёмная": "dark", "Светлая": "light", "Системная": "system"}
        theme = mapping.get(choice, "dark")
        ctk.set_appearance_mode(theme)
        self.parent.config_data["appearance"] = theme
        self.parent.update_background()

    def choose_background(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="Выбери фоновое изображение",
            filetypes=[("Изображения", "*.png *.jpg *.jpeg *.bmp *.gif"),
                       ("Все файлы", "*.*")])
        if not path:
            return
        try:
            img = Image.open(path)
            img.verify()
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось открыть:\n{e}")
            return
        self.parent.config_data["background"] = path
        save_config(self.parent.config_data)
        self.parent.update_background()
        self.parent.set_status("Фон установлен ✅", "#4CAF50")

    def reset_background(self):
        self.parent.config_data.pop("background", None)
        save_config(self.parent.config_data)
        self.parent.update_background()
        self.parent.set_status("Фон сброшен", "gray")

    def save_and_close(self):
        nickname = self.nick_entry.get().strip() or "Steve"
        self.parent.config_data["nickname"] = nickname
        save_config(self.parent.config_data)
        if not self.parent.ely_token:
            self.parent.nick_entry.configure(state="normal")
            self.parent.nick_entry.delete(0, "end")
            self.parent.nick_entry.insert(0, nickname)
        self.parent.set_status("Настройки сохранены ✅", "#4CAF50")
        self.destroy()

    def open_launcher_folder(self):
        os.startfile(LAUNCHER_DIR)

    def open_log_file(self):
        if os.path.exists(LOG_FILE):
            os.startfile(LOG_FILE)
        else:
            self.parent.set_status("Лог ещё не создан", "gray")

    def open_instances_folder(self):
        os.startfile(INSTANCES_DIR)


# ============ FAQ ============
class FAQWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("FAQ — Частые вопросы")
        self.geometry("620x680")
        self.resizable(False, False)
        self.grab_set()
        self.after(100, self.lift)
        set_icon(self)

        ctk.CTkLabel(self, text="❓  Частые вопросы",
                     font=("Arial", 22, "bold"),
                     text_color="#4CAF50").pack(pady=(20, 3))
        ctk.CTkLabel(self, text="FAQ — ответы на популярные вопросы",
                     font=("Arial", 11), text_color="gray").pack(pady=(0, 15))

        scroll = ctk.CTkScrollableFrame(self, width=560, height=550,
                                         fg_color=("gray90", "gray15"))
        scroll.pack(padx=25, pady=(0, 15), fill="both", expand=True)

        faq_items = [
            ("🔍 Как искать моды по категориям?",
             "1. Открой «🧩 Мод-браузер»\n"
             "2. Сверху есть фильтр «Категория»\n"
             "3. Выбери нужную:\n\n"
             "• 👻 Хоррор — страшные моды\n"
             "• ⚔ Снаряжение — оружие, броня\n"
             "• 🔮 Магия — магические моды\n"
             "• ⚡ Оптимизация — Sodium, Lithium\n"
             "• ⚙ Технологии — машины, механизмы\n"
             "• 🐉 Мобы — новые существа\n\n"
             "Оставь поиск пустым — покажет популярные!"),
            ("📥 Как сортировать моды?",
             "Справа от фильтра категорий есть\n"
             "«Сортировка»:\n\n"
             "• 📥 По популярности (по умолчанию)\n"
             "• 🆕 Новые\n"
             "• 🔥 Обновлённые\n"
             "• 🎯 По релевантности (для поиска)"),
            ("⚙ Почему Forge ставится не автоматически?",
             "Forge — небольшая команда. Их доход — реклама\n"
             "на официальной странице загрузки.\n\n"
             "Разработчики просят не автоматизировать установку.\n\n"
             "Мы уважаем их просьбу, но даём ТЕБЕ выбор:\n\n"
             "✅ Официальный установщик — поддержишь Forge\n"
             "❌ Автоустановка — быстро, но без поддержки"),
            ("⚙ Как установить Forge / Fabric?",
             "1. Создай экземпляр с нужной версией MC\n"
             "2. Запусти игру 1 раз (скачается ванилла)\n"
             "3. Открой настройки экземпляра (⚙ Настройки)\n"
             "4. В секции «Загрузчик модов» выбери Forge/Fabric\n"
             "5. Нажми «📥 Установить выбранный загрузчик»\n\n"
             "⚠ Для Forge 1.12.2 нужна Java 8\n"
             "⚠ Для Forge 1.17+ нужна Java 17\n"
             "⚠ Для Fabric нужна Java 17 или 21"),
            ("🧩 Как установить моды?",
             "1. Сначала установи загрузчик (Forge/Fabric)\n"
             "2. Выбери экземпляр\n"
             "3. Жми «🧩 Мод-браузер»\n"
             "4. Введи название или выбери категорию\n"
             "5. Жми «📥 Установить»\n\n"
             "Все обязательные зависимости\n"
             "скачаются АВТОМАТИЧЕСКИ!"),
            ("🌐 Как играть с друзьями?",
             "1. Все ставят Radmin VPN / Hamachi\n"
             "2. Создают общую сеть\n"
             "3. Жми «🌐 Сетевая игра»\n"
             "4. Хост: Esc → Открыть для сети\n"
             "5. Друзья вводят IP хоста"),
            ("📍 Где хранятся файлы?",
             "%APPDATA%\\.CraftLauncher\\\n\n"
             "⚙ Настройки → 📂 Открыть папку"),
            ("🎮 Не запускается Minecraft",
             "1. Проверь Java: cmd → java -version\n"
             "2. Открой консоль\n"
             "3. Увеличь RAM\n"
             "4. Посмотри launcher.log"),
            ("☕ Ошибка «Java не найдена»",
             "1. Скачай Java: java.com/download/\n"
             "2. Поставь галочку «Add to PATH»\n"
             "3. Перезапусти лаунчер\n\n"
             "MC 1.16.5- → Java 8\n"
             "MC 1.17-1.20.4 → Java 17\n"
             "MC 1.20.5+ → Java 21"),
            ("💾 Сколько RAM?",
             "• Ванилла: 2048-4096 МБ\n"
             "• С модами: 4096-8192 МБ"),
            ("🐛 Лаунчер крашится",
             "1. Открой launcher.log\n"
             "2. Найди [ERROR]\n"
             "3. Создай Issue на GitHub"),
        ]

        for q, a in faq_items:
            ctk.CTkLabel(scroll, text=q, font=("Arial", 13, "bold"),
                         text_color="#4CAF50", anchor="w", justify="left",
                         wraplength=520).pack(fill="x", padx=10, pady=(12, 3))
            ctk.CTkLabel(scroll, text=a, font=("Arial", 11), anchor="w",
                         justify="left", wraplength=520).pack(fill="x", padx=20, pady=(0, 8))

        ctk.CTkButton(self, text="Закрыть", width=200, height=40,
                      font=("Arial", 13), fg_color="#4CAF50", hover_color="#3d8b40",
                      command=self.destroy).pack(pady=(0, 20))


# ============ CHANGELOG ============
class ChangelogWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Список обновлений")
        self.geometry("520x620")
        self.resizable(False, False)
        self.grab_set()
        self.after(100, self.lift)
        set_icon(self)

        ctk.CTkLabel(self, text="📋  Список обновлений",
                     font=("Arial", 22, "bold"),
                     text_color="#4CAF50").pack(pady=(20, 3))
        ctk.CTkLabel(self, text="CraftLauncher — история версий",
                     font=("Arial", 11), text_color="gray").pack(pady=(0, 15))

        scroll = ctk.CTkScrollableFrame(self, width=460, height=480,
                                         fg_color=("gray90", "gray15"))
        scroll.pack(padx=25, pady=(0, 15), fill="both", expand=True)

        changes = [
            ("v0.99", [
                "🔍 Фильтры категорий в мод-браузере",
                "👻 Хоррор (cursed), приключения, магия и др.",
                "📥 Автозагрузка популярных модов",
                "🎯 Сортировка: популярные / новые / обновлённые",
                "🏷 Показ категорий на карточках модов",
                "🎨 Русские названия категорий",
            ]),
            ("v0.98.1", [
                "🤝 Уважение к Forge: диалог выбора",
                "✅ Официальный установщик (поддержка)",
                "❌ Автоустановка (быстро)",
            ]),
            ("v0.98", [
                "⚙ Установщик загрузчиков в настройках",
                "🔧 Поддержка Forge и Fabric",
            ]),
            ("v0.97.2", [
                "🔓 Токены не сохраняются",
                "🐛 Убраны краши",
            ]),
            ("v0.97", [
                "🔒 2FA",
                "🚪 Выход со всех устройств",
            ]),
            ("v0.96", [
                "🔗 Проверка зависимостей",
                "📦 Рекурсивная установка",
            ]),
            ("v0.95", ["🖼 Иконки модов"]),
            ("v0.94", ["🧩 Modrinth"]),
            ("v0.93", ["🌐 Сетевая игра"]),
            ("v0.92", ["❓ FAQ"]),
            ("v0.9", ["🐛 Фикс консоли"]),
            ("v0.85", ["🎨 Ely.by"]),
            ("v0.8", ["🖥 Консоль"]),
            ("v0.7", ["📋 Выбор версии"]),
            ("v0.5", ["🧠 Авто RAM"]),
            ("v0.4", ["💾 RAM-слайдер"]),
            ("v0.3", ["⚙ Настройки"]),
            ("v0.2", ["📦 Экземпляры"]),
            ("v0.1", ["🎉 Первая версия"]),
        ]

        for v, items in changes:
            h = ctk.CTkFrame(scroll, fg_color="transparent")
            h.pack(fill="x", pady=(10, 5))
            ctk.CTkLabel(h, text=f"━━━ {v} ━━━", font=("Arial", 14, "bold"),
                         text_color="#4CAF50").pack()
            for item in items:
                ctk.CTkLabel(scroll, text=f"  {item}", font=("Arial", 11),
                             anchor="w", justify="left",
                             wraplength=420).pack(fill="x", padx=10, pady=1)

        ctk.CTkButton(self, text="Закрыть", width=200, height=40,
                      font=("Arial", 13), fg_color="#4CAF50", hover_color="#3d8b40",
                      command=self.destroy).pack(pady=(0, 20))


# ============ О ЛАУНЧЕРЕ ============
class AboutWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("О лаунчере")
        self.geometry("420x560")
        self.resizable(False, False)
        self.grab_set()
        self.after(100, self.lift)
        set_icon(self)

        ctk.CTkLabel(self, text="⛏", font=("Arial", 60),
                     text_color="#4CAF50").pack(pady=(25, 5))
        ctk.CTkLabel(self, text="CraftLauncher",
                     font=("Arial", 24, "bold"),
                     text_color="#4CAF50").pack()
        ctk.CTkLabel(self, text="Beta v0.99",
                     font=("Arial", 12), text_color="gray").pack(pady=(0, 20))

        info_frame = ctk.CTkFrame(self, fg_color="transparent")
        info_frame.pack(fill="x", padx=40, pady=(0, 15))

        items = [
            ("📦 Версия", "Beta v0.99"),
            ("🐍 Python", "3.x"),
            ("📚 Библиотека", "minecraft-launcher-lib"),
            ("🎨 Скины", "Ely.by"),
            ("🌐 Сеть", "Radmin / Hamachi"),
            ("🧩 Моды", "Modrinth + Фильтры"),
            ("⚙ Загрузчики", "Forge (с выбором) + Fabric"),
            ("💾 RAM", f"{RAM_TOTAL} МБ"),
        ]

        for label, value in items:
            row = ctk.CTkFrame(info_frame, fg_color="transparent")
            row.pack(fill="x", pady=3)
            ctk.CTkLabel(row, text=label, font=("Arial", 11),
                         anchor="w", width=140).pack(side="left")
            ctk.CTkLabel(row, text=value, font=("Arial", 11, "bold"),
                         text_color="#4CAF50", anchor="w",
                         wraplength=220, justify="left").pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(self, text="Самодельный лаунчер Minecraft.\n"
                                "Создан в учебных целях. 🎓\n\n"
                                "F11 — на весь экран",
                     font=("Arial", 11), text_color="gray",
                     justify="center").pack(pady=(15, 20))

        bf = ctk.CTkFrame(self, fg_color="transparent")
        bf.pack(side="bottom", pady=20)
        ctk.CTkButton(bf, text="📂 Папка лаунчера", width=170, height=38,
                      font=("Arial", 12), fg_color="#555", hover_color="#333",
                      command=lambda: os.startfile(LAUNCHER_DIR)).pack(side="left", padx=5)
        ctk.CTkButton(bf, text="Закрыть", width=140, height=38,
                      font=("Arial", 12), fg_color="#4CAF50", hover_color="#3d8b40",
                      command=self.destroy).pack(side="left", padx=5)


# ============ ГЛАВНОЕ ОКНО ============
class Launcher(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("CraftLauncher Beta")
        self.minsize(900, 670)
        self.resizable(True, True)
        set_icon(self)
        self.config_data = load_config()

        saved_geometry = self.config_data.get("window_geometry", "1100x740+100+100")
        try:
            self.geometry(saved_geometry)
        except Exception:
            self.geometry("1100x740")

        ctk.set_appearance_mode(self.config_data.get("appearance", "dark"))

        self.is_fullscreen = False
        self.bind("<F11>", self.toggle_fullscreen)
        self.bind("<Escape>", self.exit_fullscreen)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.bg_label = ctk.CTkLabel(self, text="")
        self.bg_label.place(x=0, y=0, relwidth=1, relheight=1)
        self.bg_image_ref = None

        self.all_versions = []
        self.selected_instance = None
        self.instance_widgets = {}
        self._nick_timer = None
        self._resize_timer = None
        self.skin_photo = None

        self.ely_token = None
        self.ely_uuid = None
        self.ely_username = None

        threading.Thread(target=download_authlib, daemon=True).start()

        self.bottom_bar = ctk.CTkFrame(self, height=50, corner_radius=0,
                                        fg_color=("gray85", "gray20"))
        self.progress_frame = ctk.CTkFrame(self.bottom_bar, height=10,
                                            corner_radius=5,
                                            fg_color=("gray75", "gray25"))
        self.progress_frame.pack(fill="x", padx=20, pady=(12, 5))
        self.progress = ctk.CTkFrame(self.progress_frame, width=1, height=10,
                                      corner_radius=5, fg_color="#4CAF50")
        self.progress.place(x=0, y=0, relheight=1)
        self.progress_glow = ctk.CTkFrame(self.progress_frame, width=60, height=10,
                                           corner_radius=5, fg_color="#8BC34A")
        self.progress_glow.place(x=-100, y=0, relheight=1)
        self.percent_label = ctk.CTkLabel(self.bottom_bar, text="0%",
                                           font=("Consolas", 11, "bold"),
                                           text_color="#4CAF50")
        self.percent_label.pack(pady=(0, 8))
        self._progress_value = 0.0
        self._glow_offset = -50
        self._glow_running = False
        self.bottom_bar_visible = False

        self.top_container = ctk.CTkFrame(self, fg_color="transparent")
        self.top_container.pack(side="top", fill="both", expand=True)

        self.left_frame = ctk.CTkFrame(self.top_container, width=280,
                                        corner_radius=10,
                                        fg_color=("gray90", "gray15"))
        self.left_frame.pack(side="left", fill="y", padx=(15, 5), pady=15)
        self.left_frame.pack_propagate(False)

        ctk.CTkLabel(self.left_frame, text="📦 Экземпляры",
                     font=("Arial", 16, "bold")).pack(pady=(15, 8))

        sf = ctk.CTkFrame(self.left_frame, fg_color="transparent")
        sf.pack(fill="x", padx=15, pady=(0, 8))
        ctk.CTkLabel(sf, text="🔍", font=("Arial", 14)).pack(side="left", padx=(0, 5))
        self.instance_search = ctk.CTkEntry(sf, height=30, font=("Arial", 11),
                                             placeholder_text="Поиск...")
        self.instance_search.pack(side="left", fill="x", expand=True)
        self.instance_search.bind("<KeyRelease>", lambda e: self.refresh_instances())

        ctk.CTkButton(self.left_frame, text="➕ Создать", width=240, height=35,
                      fg_color="#4CAF50", hover_color="#3d8b40",
                      command=self.open_create_window).pack(pady=(0, 10))

        self.instances_scroll = ctk.CTkScrollableFrame(self.left_frame, width=240,
                                                        fg_color="transparent")
        self.instances_scroll.pack(pady=5, padx=10, fill="both", expand=True)

        self.right_frame = ctk.CTkFrame(self.top_container, corner_radius=10,
                                         fg_color=("gray90", "gray15"))
        self.right_frame.pack(side="right", fill="both", expand=True,
                               padx=(5, 15), pady=15)

        for x, txt, cmd in [
            (-195, "⛶", self.toggle_fullscreen),
            (-150, "ℹ", self.open_about),
            (-105, "📋", self.open_changelog),
            (-60, "❓", self.open_faq),
            (-15, "⚙", self.open_settings),
        ]:
            ctk.CTkButton(self.right_frame, text=txt, width=40, height=40,
                          font=("Arial", 18), fg_color="transparent",
                          hover_color="#3d3d3d", text_color=("black", "white"),
                          command=cmd).place(relx=1.0, rely=0.0, x=x, y=15, anchor="ne")

        self.center_frame = ctk.CTkFrame(self.right_frame, fg_color="transparent")
        self.center_frame.pack(fill="both", expand=True, pady=(70, 15), padx=40)

        ctk.CTkLabel(self.center_frame, text="⛏ CraftLauncher",
                     font=("Arial", 26, "bold"),
                     text_color="#4CAF50").pack(pady=(0, 5))
        ctk.CTkLabel(self.center_frame,
                     text=f"Beta v0.99 · RAM: {RAM_TOTAL} МБ",
                     font=("Arial", 10), text_color="gray").pack(pady=(0, 15))

        self.ely_status = ctk.CTkButton(self.center_frame,
                                         text="🔐 Войти в Ely.by",
                                         width=380, height=32,
                                         font=("Arial", 12, "bold"),
                                         fg_color="#3a3a3a",
                                         hover_color="#4a4a4a",
                                         command=self.open_ely_auth)
        self.ely_status.pack(pady=(0, 8))

        extra_btns = ctk.CTkFrame(self.center_frame, fg_color="transparent")
        extra_btns.pack(pady=(0, 12), fill="x")

        ctk.CTkButton(extra_btns, text="🌐 Сетевая игра",
                      height=36, font=("Arial", 12, "bold"),
                      fg_color="#3498db", hover_color="#2980b9",
                      command=self.open_network_window).pack(side="left", expand=True,
                                                              fill="x", padx=(0, 5))

        self.mods_btn = ctk.CTkButton(extra_btns, text="🧩 Мод-браузер",
                                       height=36, font=("Arial", 12, "bold"),
                                       fg_color="#9b59b6", hover_color="#8e44ad",
                                       command=self.open_mods_window,
                                       state="disabled")
        self.mods_btn.pack(side="left", expand=True, fill="x", padx=(5, 0))

        skin_row = ctk.CTkFrame(self.center_frame, fg_color="transparent")
        skin_row.pack(pady=(5, 12))
        self.skin_preview = ctk.CTkLabel(skin_row, text="👤", width=64, height=64,
                                          fg_color=("gray85", "gray20"),
                                          corner_radius=8, font=("Arial", 28),
                                          text_color="gray")
        self.skin_preview.pack(side="left", padx=(0, 12))

        nick_col = ctk.CTkFrame(skin_row, fg_color="transparent")
        nick_col.pack(side="left")
        ctk.CTkLabel(nick_col, text="Никнейм:",
                     font=("Arial", 12), anchor="w").pack(fill="x")
        self.nick_entry = ctk.CTkEntry(nick_col, width=300, height=35,
                                        font=("Arial", 13))
        self.nick_entry.insert(0, self.config_data.get("nickname", "Steve"))
        self.nick_entry.pack(pady=(3, 0))
        self.nick_entry.bind("<KeyRelease>", self.on_nick_change)

        self.instance_info = ctk.CTkLabel(self.center_frame,
                                           text="Выбери экземпляр слева",
                                           font=("Arial", 13),
                                           text_color="gray")
        self.instance_info.pack(pady=(5, 3))

        self.ram_info = ctk.CTkLabel(self.center_frame, text="",
                                      font=("Arial", 11),
                                      text_color="#4CAF50")
        self.ram_info.pack(pady=(0, 12))

        self.status_label = ctk.CTkLabel(self.center_frame,
                                          text="Готов к запуску",
                                          font=("Arial", 11),
                                          text_color="gray",
                                          wraplength=380)
        self.status_label.pack(pady=(0, 15))

        self.play_button = ctk.CTkButton(
            self.center_frame, text="▶  ИГРАТЬ", width=380, height=50,
            font=("Arial", 16, "bold"), fg_color="#4CAF50", hover_color="#3d8b40",
            command=self.start_game_thread, state="disabled")
        self.play_button.pack(pady=(5, 10))

        inst_btns = ctk.CTkFrame(self.center_frame, fg_color="transparent")
        inst_btns.pack(pady=(0, 10))
        self.open_folder_button = ctk.CTkButton(inst_btns, text="📂 Папка",
                                                 width=120, height=30,
                                                 font=("Arial", 11),
                                                 fg_color="#3a3a3a",
                                                 hover_color="#4a4a4a",
                                                 command=self.open_instance_folder,
                                                 state="disabled")
        self.open_folder_button.pack(side="left", padx=(0, 5))
        self.edit_button = ctk.CTkButton(inst_btns, text="⚙ Настройки",
                                          width=120, height=30,
                                          font=("Arial", 11), fg_color="#3a3a3a",
                                          hover_color="#4a4a4a",
                                          command=self.edit_selected,
                                          state="disabled")
        self.edit_button.pack(side="left", padx=(0, 5))
        self.delete_button = ctk.CTkButton(inst_btns, text="🗑 Удалить",
                                            width=120, height=30,
                                            font=("Arial", 11),
                                            fg_color="#5a2a2a",
                                            hover_color="#7a2020",
                                            command=self.delete_selected,
                                            state="disabled")
        self.delete_button.pack(side="left")

        self.bind("<Configure>", self.on_window_resize)
        threading.Thread(target=self.load_versions, daemon=True).start()
        self.refresh_instances()
        self.update_ely_status()
        self.after(100, self.update_background)

    def on_close(self):
        try:
            self.config_data["window_geometry"] = self.geometry()
            save_config(self.config_data)
        except Exception:
            pass
        self.destroy()

    def show_progress_bar(self):
        if not self.bottom_bar_visible:
            self.bottom_bar.pack(side="bottom", fill="x")
            self.bottom_bar_visible = True

    def hide_progress_bar(self):
        if self.bottom_bar_visible:
            self.bottom_bar.pack_forget()
            self.bottom_bar_visible = False
            self._progress_value = 0.0
            self.progress.configure(width=1)
            self.percent_label.configure(text="0%")

    def toggle_fullscreen(self, event=None):
        self.is_fullscreen = not self.is_fullscreen
        self.attributes("-fullscreen", self.is_fullscreen)

    def exit_fullscreen(self, event=None):
        if self.is_fullscreen:
            self.is_fullscreen = False
            self.attributes("-fullscreen", False)

    def on_window_resize(self, event=None):
        if event and event.widget != self:
            return
        if self._resize_timer:
            self.after_cancel(self._resize_timer)
        self._resize_timer = self.after(200, self.update_background)

    def get_default_background(self, w, h):
        is_dark = ctk.get_appearance_mode() == "Dark"
        c1, c2 = ((26, 40, 34), (18, 22, 38)) if is_dark else ((225, 245, 230), (220, 235, 250))
        img = Image.new("RGB", (1, h))
        pixels = img.load()
        for i in range(h):
            t = i / max(h - 1, 1)
            r = int(c1[0] + (c2[0] - c1[0]) * t)
            g = int(c1[1] + (c2[1] - c1[1]) * t)
            b = int(c1[2] + (c2[2] - c1[2]) * t)
            pixels[0, i] = (r, g, b)
        return img.resize((w, h), Image.NEAREST)

    def update_background(self, event=None):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 10 or h < 10:
            return
        current_bg = self.config_data.get("background")
        if (hasattr(self, '_last_bg') and
                self._last_bg == (current_bg, w, h, ctk.get_appearance_mode())):
            return
        self._last_bg = (current_bg, w, h, ctk.get_appearance_mode())

        if current_bg and os.path.exists(current_bg):
            try:
                img = Image.open(current_bg).convert("RGB")
                ir = img.width / img.height
                wr = w / h
                if ir > wr:
                    nw = int(h * ir)
                    img = img.resize((nw, h), Image.LANCZOS)
                    left = (nw - w) // 2
                    img = img.crop((left, 0, left + w, h))
                else:
                    nh = int(w / ir)
                    img = img.resize((w, nh), Image.LANCZOS)
                    top = (nh - h) // 2
                    img = img.crop((0, top, w, top + h))
                dark = Image.new("RGB", (w, h), (0, 0, 0))
                img = Image.blend(img, dark, alpha=0.4)
            except Exception:
                img = self.get_default_background(w, h)
        else:
            img = self.get_default_background(w, h)

        ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(w, h))
        self.bg_label.configure(image=ctk_img)
        self.bg_image_ref = ctk_img
        self.bg_label.lower()

    def set_progress(self, value):
        self._progress_value = max(0.0, min(1.0, value))
        self.update_idletasks()
        tw = self.progress_frame.winfo_width()
        if tw < 10:
            tw = self.winfo_width() - 40
        nw = int(tw * self._progress_value)
        self.progress.configure(width=max(1, nw))
        self.percent_label.configure(text=f"{int(self._progress_value * 100)}%")
        if 0 < self._progress_value < 1.0:
            if not self._glow_running:
                self._glow_running = True
                self.animate_glow()
        else:
            self._glow_running = False
            self.progress_glow.place(x=-100)

    def animate_glow(self):
        if not self._glow_running:
            return
        self.update_idletasks()
        tw = self.progress_frame.winfo_width()
        if tw < 10:
            tw = self.winfo_width() - 40
        self._glow_offset += 10
        if self._glow_offset > tw:
            self._glow_offset = -60
        fw = int(tw * self._progress_value)
        if self._glow_offset < fw:
            self.progress_glow.place(x=self._glow_offset, y=0, relheight=1)
        else:
            self.progress_glow.place(x=-100, y=0, relheight=1)
        self.after(30, self.animate_glow)

    def open_ely_auth(self):
        ElyAuthWindow(self, self.on_ely_success)

    def on_ely_success(self, result):
        self.ely_token = result["accessToken"]
        self.ely_uuid = result["uuid"]
        self.ely_username = result["name"]
        self.update_ely_status()
        self.set_status(f"✅ Вход: {self.ely_username}", "#4CAF50")

    def logout_ely(self):
        self.ely_token = None
        self.ely_uuid = None
        self.ely_username = None
        self.update_ely_status()
        self.set_status("Вышел из Ely.by", "gray")

    def update_ely_status(self):
        if self.ely_token and self.ely_username:
            self.ely_status.configure(text=f"✅ {self.ely_username} (выйти)",
                                       fg_color="#2d5a2d", hover_color="#3d7a3d")
            self.ely_status.configure(command=self.logout_ely)
            self.nick_entry.configure(state="disabled")
            self.nick_entry.delete(0, "end")
            self.nick_entry.insert(0, self.ely_username)
            self.update_skin_preview(self.ely_username)
        else:
            self.ely_status.configure(text="🔐 Войти в Ely.by",
                                       fg_color="#3a3a3a", hover_color="#4a4a4a")
            self.ely_status.configure(command=self.open_ely_auth)
            self.nick_entry.configure(state="normal")
            self.nick_entry.delete(0, "end")
            self.nick_entry.insert(0, self.config_data.get("nickname", "Steve"))
            self.update_skin_preview(self.nick_entry.get())

    def on_nick_change(self, event=None):
        if self.ely_token:
            return
        if self._nick_timer:
            self.after_cancel(self._nick_timer)
        self._nick_timer = self.after(600, self.update_skin_preview_from_entry)

    def update_skin_preview_from_entry(self):
        self.update_skin_preview(self.nick_entry.get().strip())

    def update_skin_preview(self, nickname):
        if not nickname:
            self.skin_preview.configure(image=None, text="👤")
            return

        def fetch():
            try:
                img = load_skin_image(nickname)
                if img:
                    head = crop_head_from_skin(img)
                    self.after(0, lambda h=head: self._apply_skin(h))
                else:
                    self.after(0, lambda: self.skin_preview.configure(image=None, text="👤"))
            except Exception as e:
                log(f"skin fetch error: {e}", "WARN")

        threading.Thread(target=fetch, daemon=True).start()

    def _apply_skin(self, pil_image):
        try:
            ctk_img = ctk.CTkImage(light_image=pil_image, dark_image=pil_image,
                                    size=(64, 64))
            self.skin_preview.configure(image=ctk_img, text="")
            self.skin_photo = ctk_img
        except Exception:
            self.skin_preview.configure(image=None, text="👤")

    def load_versions(self):
        self.set_status("Загрузка списка версий...")
        try:
            versions = minecraft_launcher_lib.utils.get_available_versions(LAUNCHER_DIR)
            releases = [v["id"] for v in versions if v["type"] == "release"]
            releases = sort_versions(releases)
            self.all_versions = releases
            self.set_status(f"Загружено версий: {len(releases)} ✅")
        except Exception as e:
            self.set_status(f"Ошибка: {str(e)[:50]} ❌")

    def refresh_instances(self):
        for widget in self.instances_scroll.winfo_children():
            widget.destroy()
        self.instance_widgets.clear()
        all_instances = list_instances()
        query = self.instance_search.get().strip().lower()
        instances = ([i for i in all_instances if query in i["name"].lower()]
                     if query else all_instances)

        if not all_instances:
            ctk.CTkLabel(self.instances_scroll,
                         text="Нет экземпляров.\nНажми ➕ Создать",
                         font=("Arial", 12), text_color="gray").pack(pady=30)
            return
        if not instances:
            ctk.CTkLabel(self.instances_scroll,
                         text=f"Ничего не найдено\nпо запросу «{query}»",
                         font=("Arial", 11), text_color="gray").pack(pady=20)
            return

        for inst in instances:
            name = inst["name"]
            version = inst["version"]
            ram = inst.get("ram", 2048)
            mod_loader = inst.get("mod_loader", "vanilla")

            text = f"🎮 {name}\n{version}"
            if mod_loader != "vanilla":
                text += f" [{mod_loader}]"
            text += f" · {ram} МБ"

            btn = ctk.CTkButton(self.instances_scroll, text=text,
                                 width=220, height=60, font=("Arial", 11),
                                 anchor="w",
                                 fg_color="#4CAF50" if name == self.selected_instance else "#2b2b2b",
                                 hover_color="#3d8b40",
                                 command=lambda n=name: self.select_instance(n))
            btn.pack(pady=3, padx=5, fill="x")
            self.instance_widgets[name] = btn

    def update_play_button(self):
        if not self.selected_instance:
            self.play_button.configure(text="▶  ИГРАТЬ", state="disabled")
            return
        try:
            with open(instance_config_path(self.selected_instance), "r",
                      encoding="utf-8") as f:
                data = json.load(f)
            version = data.get("version", "")
            launch_version = data.get("launch_version", version)
            if is_version_installed(self.selected_instance, launch_version):
                self.play_button.configure(text="▶  ИГРАТЬ", state="normal")
            else:
                self.play_button.configure(text="⬇  УСТАНОВИТЬ", state="normal")
        except Exception:
            pass

    def select_instance(self, name):
        self.selected_instance = name
        for n, btn in self.instance_widgets.items():
            btn.configure(fg_color="#4CAF50" if n == name else "#2b2b2b")
        try:
            with open(instance_config_path(name), "r", encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("ram", 2048)
            data.setdefault("mod_loader", "vanilla")

            info_text = f"Выбран: {data['name']}  ·  {data['version']}"
            if data.get("mod_loader", "vanilla") != "vanilla":
                info_text += f" [{data['mod_loader']}]"

            self.instance_info.configure(text=info_text,
                                          text_color=("black", "white"))
            self.ram_info.configure(text=f"💾 RAM: {data['ram']} МБ")
            self.delete_button.configure(state="normal")
            self.edit_button.configure(state="normal")
            self.open_folder_button.configure(state="normal")
            self.mods_btn.configure(state="normal")
            self.update_play_button()
        except Exception:
            pass

    def edit_selected(self):
        if self.selected_instance:
            EditInstanceWindow(self, self.selected_instance, self.on_instance_edited)

    def on_instance_edited(self):
        self.refresh_instances()
        if self.selected_instance:
            self.select_instance(self.selected_instance)

    def open_instance_folder(self):
        if not self.selected_instance:
            return
        mc_dir = instance_minecraft_dir(self.selected_instance)
        if os.path.exists(mc_dir):
            os.startfile(mc_dir)

    def delete_selected(self):
        if not self.selected_instance:
            return
        confirm = ctk.CTkToplevel(self)
        confirm.title("Подтверждение")
        confirm.geometry("360x180")
        confirm.resizable(False, False)
        confirm.grab_set()
        confirm.after(100, confirm.lift)
        set_icon(confirm)
        ctk.CTkLabel(confirm,
                     text=f"Удалить экземпляр\n«{self.selected_instance}»?",
                     font=("Arial", 13)).pack(pady=(20, 5))
        ctk.CTkLabel(confirm, text="Все миры и моды будут удалены!",
                     font=("Arial", 10), text_color="#e74c3c").pack()
        frame = ctk.CTkFrame(confirm, fg_color="transparent")
        frame.pack(pady=15)

        def do_delete():
            delete_instance(self.selected_instance)
            self.selected_instance = None
            self.instance_info.configure(text="Выбери экземпляр слева",
                                          text_color="gray")
            self.ram_info.configure(text="")
            self.play_button.configure(state="disabled", text="▶  ИГРАТЬ")
            self.delete_button.configure(state="disabled")
            self.edit_button.configure(state="disabled")
            self.open_folder_button.configure(state="disabled")
            self.mods_btn.configure(state="disabled")
            self.refresh_instances()
            confirm.destroy()

        ctk.CTkButton(frame, text="Удалить", width=120, height=35,
                      fg_color="#e74c3c", hover_color="#c0392b",
                      command=do_delete).pack(side="left", padx=5)
        ctk.CTkButton(frame, text="Отмена", width=120, height=35,
                      fg_color="#555", hover_color="#333",
                      command=confirm.destroy).pack(side="left", padx=5)

    def open_create_window(self):
        if not self.all_versions:
            self.set_status("Версии загружаются...")
            return
        CreateInstanceWindow(self, self.all_versions, self.on_instance_created)

    def on_instance_created(self):
        self.refresh_instances()
        self.set_status("Экземпляр создан ✅", "#4CAF50")

    def open_settings(self):
        SettingsWindow(self)

    def open_about(self):
        AboutWindow(self)

    def open_changelog(self):
        ChangelogWindow(self)

    def open_faq(self):
        FAQWindow(self)

    def open_network_window(self):
        NetworkWindow(self)

    def open_mods_window(self):
        if not self.selected_instance:
            self.set_status("Сначала выбери экземпляр", "#e74c3c")
            return
        try:
            with open(instance_config_path(self.selected_instance), "r",
                      encoding="utf-8") as f:
                data = json.load(f)
            mc_version = data.get("version", "1.20.1")
            ModsWindow(self, self.selected_instance, mc_version)
        except Exception as e:
            self.set_status(f"Ошибка: {e}", "#e74c3c")

    def set_status(self, text, color="gray"):
        self.status_label.configure(text=text, text_color=color)
        self.update()

    def open_quick_connect(self, ip, port):
        if not self.selected_instance:
            self.set_status("Выбери экземпляр", "#e74c3c")
            return
        instance_name = self.selected_instance
        try:
            with open(instance_config_path(instance_name), "r",
                      encoding="utf-8") as f:
                inst_data = json.load(f)
            version = inst_data["version"]
            launch_version = inst_data.get("launch_version", version)
            ram = inst_data.get("ram", 2048)
            mc_dir = instance_minecraft_dir(instance_name)

            if not is_version_installed(instance_name, launch_version):
                self.set_status("Сначала установи версию", "#e74c3c")
                return

            use_ely = bool(self.ely_token and self.ely_uuid and self.ely_username)
            nickname = self.ely_username if use_ely else (
                self.nick_entry.get().strip() or "Player")

            console = None
            if self.config_data.get("show_console", True):
                console = ConsoleWindow(self, instance_name)
                console.add_message(f"Подключение к {ip}:{port}...", "info")

            if use_ely:
                options = {"username": self.ely_username, "uuid": self.ely_uuid,
                           "token": self.ely_token, "gameDirectory": mc_dir,
                           "jvmArguments": [f"-Xmx{ram}M", f"-Xms{min(ram, 1024)}M"]}
                if os.path.exists(AUTHLIB_JAR):
                    options["jvmArguments"].insert(0, f"-javaagent:{AUTHLIB_JAR}=ely.by")
            else:
                options = {"username": nickname, "uuid": "0", "token": "0",
                           "gameDirectory": mc_dir,
                           "jvmArguments": [f"-Xmx{ram}M", f"-Xms{min(ram, 1024)}M"]}

            command = minecraft_launcher_lib.command.get_minecraft_command(
                launch_version, mc_dir, options)
            command.extend(["--server", ip, "--port", str(port)])

            self.set_status(f"Запуск → {ip}:{port}", "#4CAF50")
            self.launch_process(command, mc_dir, console)
        except Exception as e:
            self.set_status(f"Ошибка: {e}", "#e74c3c")

    def start_game_thread(self):
        if not self.selected_instance:
            return
        try:
            current_text = self.play_button.cget("text")
            self.play_button.configure(state="disabled", text="Загрузка...")
            threading.Thread(target=self.launch_game, args=(current_text,),
                              daemon=True).start()
        except Exception as e:
            import traceback
            log(f"start_game_thread ERROR: {traceback.format_exc()}", "ERROR")
            self.set_status(f"Ошибка: {str(e)[:60]}", "#e74c3c")
            self.play_button.configure(state="normal", text="▶  ИГРАТЬ")

    def launch_game(self, button_text):
        console = None
        try:
            log(f"=== launch_game START ===")
            name = self.selected_instance
            use_ely = bool(self.ely_token and self.ely_uuid and self.ely_username)
            nickname = self.ely_username if use_ely else (
                self.nick_entry.get().strip() or "Player")
            if not use_ely:
                self.config_data["nickname"] = nickname
                save_config(self.config_data)

            with open(instance_config_path(name), "r", encoding="utf-8") as f:
                inst_data = json.load(f)
            version = inst_data["version"]
            launch_version = inst_data.get("launch_version", version)
            ram = inst_data.get("ram", 2048)
            mc_dir = instance_minecraft_dir(name)

            already_installed = is_version_installed(name, launch_version)
            is_installing = "УСТАНОВИТЬ" in button_text

            if already_installed and not is_installing:
                if self.config_data.get("show_console", True):
                    console = ConsoleWindow(self, name)
                    console.add_message(f"Версия: {launch_version}", "system")
                    console.add_message(f"Ник: {nickname}", "system")
                    if use_ely:
                        console.add_message("🎨 ONLINE (Ely.by)", "ok")
                    else:
                        console.add_message("💤 OFFLINE", "warn")

                if use_ely:
                    options = {"username": self.ely_username, "uuid": self.ely_uuid,
                               "token": self.ely_token, "gameDirectory": mc_dir,
                               "jvmArguments": [f"-Xmx{ram}M", f"-Xms{min(ram, 1024)}M"]}
                    if os.path.exists(AUTHLIB_JAR):
                        options["jvmArguments"].insert(0, f"-javaagent:{AUTHLIB_JAR}=ely.by")
                else:
                    options = {"username": nickname, "uuid": "0", "token": "0",
                               "gameDirectory": mc_dir,
                               "jvmArguments": [f"-Xmx{ram}M", f"-Xms{min(ram, 1024)}M"]}

                command = minecraft_launcher_lib.command.get_minecraft_command(
                    launch_version, mc_dir, options)
                self.launch_process(command, mc_dir, console)
                self.set_status(f"«{name}» запущен! 🎮", "#4CAF50")
                return

            self.after(0, self.show_progress_bar)
            if self.config_data.get("show_console", True):
                console = ConsoleWindow(self, name)
                console.add_message(f"Установка Minecraft {version}...", "info")

            self.set_status(f"Установка {version}...")
            self.set_progress(0)
            self._progress_max = 1

            def scb(t): self.set_status(t[:60])
            def mcb(m): self._progress_max = m if m > 0 else 1
            def pcb(c):
                if self._progress_max > 0:
                    self.set_progress(c / self._progress_max)

            try:
                minecraft_launcher_lib.install.install_minecraft_version(
                    version, mc_dir,
                    callback={"setStatus": scb, "setProgress": pcb, "setMax": mcb})
            except Exception as e:
                self.set_status(f"Ошибка: {e}"[:80], "#e74c3c")
                self.after(0, self.hide_progress_bar)
                return

            self.set_progress(1.0)
            self.set_status("Ванилла установлена ✅")
            self.after(1500, self.hide_progress_bar)

            mod_loader = inst_data.get("mod_loader", "vanilla")
            if mod_loader != "vanilla":
                self.set_status(
                    f"Ванилла установлена. Установи {mod_loader.upper()} в настройках.",
                    "#f39c12"
                )
                self.after(0, self.update_play_button)
                return

            if not self.config_data.get("auto_launch_after_install", True):
                self.after(0, self.update_play_button)
                return

            if use_ely:
                options = {"username": self.ely_username, "uuid": self.ely_uuid,
                           "token": self.ely_token, "gameDirectory": mc_dir,
                           "jvmArguments": [f"-Xmx{ram}M", f"-Xms{min(ram, 1024)}M"]}
                if os.path.exists(AUTHLIB_JAR):
                    options["jvmArguments"].insert(0, f"-javaagent:{AUTHLIB_JAR}=ely.by")
            else:
                options = {"username": nickname, "uuid": "0", "token": "0",
                           "gameDirectory": mc_dir,
                           "jvmArguments": [f"-Xmx{ram}M", f"-Xms{min(ram, 1024)}M"]}

            command = minecraft_launcher_lib.command.get_minecraft_command(
                version, mc_dir, options)
            self.launch_process(command, mc_dir, console)
            self.set_status(f"«{name}» запущен! 🎮", "#4CAF50")
        except Exception as e:
            import traceback
            err = traceback.format_exc()
            log(f"CRASH in launch_game: {err}", "ERROR")
            print(err)
            self.set_status(f"Ошибка: {str(e)[:80]}", "#e74c3c")
            self.after(0, self.hide_progress_bar)
        finally:
            self.after(0, lambda: self.update_play_button())

    def launch_process(self, command, cwd, console):
        try:
            process = subprocess.Popen(
                command, cwd=cwd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW,
                bufsize=1, universal_newlines=True,
                encoding="utf-8", errors="replace")
            if console:
                console.process = process

            def read_output():
                try:
                    for line in iter(process.stdout.readline, ""):
                        if not line:
                            break
                        line = line.rstrip()
                        low = line.lower()
                        level = ("error" if any(k in low for k in
                                 ["error", "exception", "caused by", "fatal"])
                                 else "warn" if "warn" in low
                                 else "info" if "done" in low and "for help" in low
                                 else "normal")
                        if console:
                            try:
                                console.after(0, lambda l=line, lv=level: console.append_log(l, lv))
                            except Exception:
                                pass
                    code = process.wait()
                    if console:
                        try:
                            if code == 0:
                                console.after(0, lambda: console.add_message("Игра завершена", "ok"))
                            else:
                                console.after(0, lambda c=code: console.add_message(f"Код выхода: {c}", "error"))
                        except Exception:
                            pass
                except Exception:
                    pass

            threading.Thread(target=read_output, daemon=True).start()
        except FileNotFoundError as e:
            if console:
                try:
                    console.after(0, lambda: console.add_message(f"Java не найдена!\n{e}", "error"))
                except Exception:
                    pass
        except Exception as e:
            if console:
                try:
                    console.after(0, lambda: console.add_message(f"Ошибка: {e}", "error"))
                except Exception:
                    pass


# ============ ЗАПУСК ============
if __name__ == "__main__":
    try:
        app = Launcher()
        app.mainloop()
    except Exception as e:
        log(f"FATAL: {e}", "ERROR")
        import traceback
        log(traceback.format_exc(), "ERROR")
        raise
    finally:
        log("CraftLauncher closed")