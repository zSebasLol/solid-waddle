import sys
import os
import importlib.util
import json
import time
import atexit

try:
    import readline
    readline.parse_and_bind(r'\e[3~: delete-char')
except ImportError:
    pass

VERSION = "1.0.0"
LINKS_JSON_URL = "https://d0ce3.github.io/d0ce3-Addons/data/links.json"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, "__megacmd_cache__")
PACKAGE_DIR = os.path.join(CACHE_DIR, "modules")
AUTOBACKUP_FLAG_FILE = os.path.join(CACHE_DIR, ".autobackup_init")

def ensure_requests():
    try:
        import requests
        return requests
    except ImportError:
        import subprocess
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "requests"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
        import requests
        return requests

requests = ensure_requests()

class ConfigManager:
    _config = None
    _last_check = 0
    
    @staticmethod
    def load(force=False):
        if not force and ConfigManager._config and (time.time() - ConfigManager._last_check) < 300:
            return ConfigManager._config
        
        try:
            response = requests.get(LINKS_JSON_URL, timeout=15)
            if response.status_code != 200:
                return ConfigManager._config
            
            config = response.json()
            ConfigManager._config = config.get("megacmd", {})
            ConfigManager._last_check = time.time()
            return ConfigManager._config
        except Exception:
            return ConfigManager._config
    
    @staticmethod
    def get_package_url():
        config = ConfigManager.load()
        return config.get("package") if config else None
    
    @staticmethod
    def get_remote_version():
        config = ConfigManager.load()
        return config.get("version") if config else None

class AutobackupManager:
    @staticmethod
    def is_initialized():
        if not os.path.exists(AUTOBACKUP_FLAG_FILE):
            return False
        
        try:
            with open(AUTOBACKUP_FLAG_FILE, 'r') as f:
                data = json.load(f)
            
            init_time = data.get('init_time', 0)
            if time.time() - init_time > 7200:
                return False
            
            pid = data.get('pid', 0)
            if pid != os.getpid():
                try:
                    os.kill(pid, 0)
                    return True
                except (OSError, ProcessLookupError):
                    return False
            
            return True
        except:
            return False
    
    @staticmethod
    def mark_initialized():
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(AUTOBACKUP_FLAG_FILE, 'w') as f:
                json.dump({'init_time': time.time(), 'version': VERSION, 'pid': os.getpid()}, f)
            return True
        except:
            return False
    
    @staticmethod
    def clear_flag():
        try:
            if os.path.exists(AUTOBACKUP_FLAG_FILE):
                os.remove(AUTOBACKUP_FLAG_FILE)
            return True
        except:
            return False

class ModuleLoader:
    _cache = {}
    _package_manager = None
    
    @staticmethod
    def _ensure_package_manager_available():
        if ModuleLoader._package_manager is not None:
            return ModuleLoader._package_manager
        
        module_file = os.path.join(PACKAGE_DIR, "package_manager.py")
        if not os.path.exists(module_file):
            return None
        
        try:
            with open(module_file, 'r', encoding='utf-8', errors='ignore') as f:
                source_code = f.read().replace('\x00', '').replace('\r\n', '\n')
            
            spec = importlib.util.spec_from_loader("package_manager", loader=None)
            module = importlib.util.module_from_spec(spec)
            
            module.__dict__.update({
                '__file__': module_file,
                '__name__': "package_manager",
                'ModuleLoader': ModuleLoader,
                'CloudModuleLoader': ModuleLoader
            })
            
            exec(source_code, module.__dict__)
            
            if hasattr(module, 'set_directories'):
                module.set_directories(CACHE_DIR, PACKAGE_DIR, LINKS_JSON_URL)
            
            ModuleLoader._package_manager = module
            return module
        except Exception:
            return None
    
    @staticmethod
    def _bootstrap_ensure_installed():
        if os.path.exists(PACKAGE_DIR) and len(os.listdir(PACKAGE_DIR)) > 0:
            return True
        
        try:
            package_url = ConfigManager.get_package_url()
            if not package_url:
                return False
            
            response = requests.get(package_url, timeout=60)
            if response.status_code != 200:
                return False
            
            import tempfile, zipfile, shutil
            
            temp_zip = os.path.join(tempfile.gettempdir(), "megacmd_temp.zip")
            with open(temp_zip, 'wb') as f:
                f.write(response.content)
            
            if os.path.exists(CACHE_DIR):
                shutil.rmtree(CACHE_DIR)
            
            os.makedirs(CACHE_DIR, exist_ok=True)
            
            with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
                for member in zip_ref.namelist():
                    if member.startswith('modules/') or member.startswith('core/'):
                        target_path = os.path.join(CACHE_DIR, member)
                        
                        os.makedirs(os.path.dirname(target_path), exist_ok=True)
                        
                        if not member.endswith('/'):
                            with zip_ref.open(member) as source:
                                with open(target_path, 'wb') as target:
                                    target.write(source.read())
            
            os.remove(temp_zip)
            return True
        except Exception:
            return False
    
    @staticmethod
    def load_module(module_name):
        if module_name in ModuleLoader._cache:
            return ModuleLoader._cache[module_name]
        
        pm = ModuleLoader._ensure_package_manager_available()
        if pm:
            if not pm.PackageManager.ensure_installed():
                return None
        else:
            if not ModuleLoader._bootstrap_ensure_installed():
                return None
        
        if '.' in module_name:
            parts = module_name.split('.')
            base_dir = CACHE_DIR
            for part in parts[:-1]:
                base_dir = os.path.join(base_dir, part)
            module_file = os.path.join(base_dir, f"{parts[-1]}.py")
        else:
            module_file = os.path.join(PACKAGE_DIR, f"{module_name}.py")
        
        if not os.path.exists(module_file):
            return None
        
        try:
            with open(module_file, 'r', encoding='utf-8', errors='ignore') as f:
                source_code = f.read().replace('\x00', '').replace('\r\n', '\n')
            
            if not source_code.strip():
                return None
            
            spec = importlib.util.spec_from_loader(module_name, loader=None)
            module = importlib.util.module_from_spec(spec)
            
            if CACHE_DIR not in sys.path:
                sys.path.insert(0, CACHE_DIR)
            
            module.__dict__.update({
                '__file__': module_file,
                '__name__': module_name,
                'ModuleLoader': ModuleLoader,
                'CloudModuleLoader': ModuleLoader,
                'megacmd_tool': sys.modules[__name__],
                'SCRIPT_BASE_DIR': BASE_DIR
            })
            
            exec(source_code, module.__dict__)
            
            sys.modules[module_name] = module
            ModuleLoader._cache[module_name] = module
            
            return module
        except Exception as e:
            print(f"⚠  Error cargando modulo {module_name}: {e}")
            return None
    
    @staticmethod
    def reload_all():
        remote_version = ConfigManager.get_remote_version()
        if remote_version:
            print(f"🔌 Versión local: {VERSION} | Versión remota: {remote_version}")
        
        ModuleLoader._cache.clear()
        ModuleLoader._package_manager = None
        
        for key in list(sys.modules.keys()):
            if key in ['config', 'utils', 'megacmd', 'backup', 'files', 'autobackup', 
                      'logger', 'menu', 'package_manager', 'dc_menu', 'dc_codespace', 
                      'discord_notifier']:
                del sys.modules[key]
        
        pm = ModuleLoader._ensure_package_manager_available()
        if pm:
            success = pm.PackageManager.reload_modules()
        else:
            success = ModuleLoader._bootstrap_ensure_installed()
        
        if success:
            AutobackupManager.clear_flag()
        
        return success

CloudModuleLoader = ModuleLoader

def call_module_function(module_name, function_name):
    module = ModuleLoader.load_module(module_name)
    if module and hasattr(module, function_name):
        getattr(module, function_name)()
    else:
        print(f"âŒ Error: funcion {function_name} no disponible")
        input("\n[+] Enter para continuar...")

def get_menu_instances():
    config = ModuleLoader.load_module("config")
    utils = ModuleLoader.load_module("utils")
    backup = ModuleLoader.load_module("backup")
    autobackup = ModuleLoader.load_module("autobackup")
    menu = ModuleLoader.load_module("menu")
    
    if not all([config, utils, backup, autobackup, menu]):
        return None, None
    
    menu_backup = menu.MenuBackup(config, utils, backup, autobackup)
    menu_archivos = menu.MenuArchivos(config, utils, backup, autobackup)
    
    return menu_backup, menu_archivos

ejecutar_backup_manual = lambda: (lambda m: m[0].crear_backup_manual() if m[0] else call_module_function("backup", "ejecutar_backup_manual"))(get_menu_instances())

listar_y_descargar_mega = lambda: (lambda m: m[1].listar_y_descargar() if m[1] else call_module_function("files", "listar_y_descargar"))(get_menu_instances())

gestionar_backups_mega = lambda: (lambda m: m[1].gestionar_backups() if m[1] else call_module_function("files", "gestionar_backups"))(get_menu_instances())

subir_archivo_mega = lambda: (lambda m: m[1].subir_archivo() if m[1] else call_module_function("files", "subir_archivo"))(get_menu_instances())

configurar_autobackup = lambda: (lambda m: m[0].configurar_autobackup() if m[0] else call_module_function("backup", "configurar_autobackup"))(get_menu_instances())

info_cuenta_mega = lambda: (lambda m: m[1].info_cuenta() if m[1] else call_module_function("files", "info_cuenta"))(get_menu_instances())

toggle_autobackup = configurar_autobackup

def menu_discord():
    call_module_function("dc_menu", "menu_principal_discord")

def actualizar_modulos():
    print("\n" + "="*60)
    print("🔄 ACTUALIZAR MÓDULOS")
    print("="*60 + "\n")
    
    if input("¿Continuar con la actualización? (s/n): ").strip().lower() == 's':
        success = ModuleLoader.reload_all()
        print("\n✅ Actualizado" if success else "\n❌ Error en actualización")
    else:
        print("\n❌ Cancelado")
    
    input("Enter para continuar...")

def init():
    ConfigManager.load()
    
    pm = ModuleLoader._ensure_package_manager_available()
    if pm:
        if not pm.PackageManager.ensure_installed():
            return
    else:
        if not ModuleLoader._bootstrap_ensure_installed():
            return
    
    config = ModuleLoader.load_module("config")
    if not config:
        return
    
    logger_mod = ModuleLoader.load_module("logger")
    if logger_mod and config.CONFIG.get("debug_enabled", False):
        logger_mod.logger_manager.enable_debug()

    utils = ModuleLoader.load_module("utils")
    try:
        logger_observer = ModuleLoader.load_module("logger_observer")
        discord_observer = ModuleLoader.load_module("discord_observer")
        if logger_observer:
            logger_observer.setup_logger_observer()
        if discord_observer:
            discord_observer.setup_discord_observer()
        if utils and hasattr(utils, "logger"):
            utils.logger.debug("Sistema de eventos inicializado")
    except Exception as e:
        if utils and hasattr(utils, "logger"):
            utils.logger.warning(f"No se pudo inicializar eventos: {e}")

    if AutobackupManager.is_initialized():
        return
    
    autobackup = ModuleLoader.load_module("autobackup")
    if autobackup and hasattr(autobackup, 'start_autobackup'):
        try:
            AutobackupManager.mark_initialized()
            if config.CONFIG.get("autobackup_enabled", False):
                autobackup.start_autobackup()
        except Exception:
            AutobackupManager.clear_flag()

init()

@atexit.register
def cleanup_on_exit():
    try:
        if os.path.exists(AUTOBACKUP_FLAG_FILE):
            with open(AUTOBACKUP_FLAG_FILE, 'r') as f:
                if json.load(f).get('pid') == os.getpid():
                    AutobackupManager.clear_flag()
    except:
        pass
