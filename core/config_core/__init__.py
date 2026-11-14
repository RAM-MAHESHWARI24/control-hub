"""
Homelab host library (config_core)

Standard-library-only helpers shared by the Setup Wizard (setup/) and the
Control Hub daemon: hardware probing, storage and hardlink checks, port
collision scans, secrets, Netplan management, .env rendering, canonical
install paths and bearer-token auth.

Installer orchestration (deploying stacks, writing host units) lives in
setup/installer and is not part of this library.
"""

from .paths import (
    ETC_DIR,
    STATE_DIR,
    APPDATA_DIR,
    CONFIG_FILE,
    MANIFEST_FILE,
    CONTROL_HUB_TOKEN_FILE,
    SERVICE_USER,
    module_env_file,
    module_appdata_dir,
    is_linux_host,
)
from .auth_token import (
    generate_token,
    write_token_file,
    read_token_file,
    load_control_hub_token,
    extract_token,
    token_matches,
)
from .secrets_generator import generate_password, generate_api_key, generate_all_secrets
from .port_manager import check_port, check_ports_matrix, get_default_ports
from .storage_manager import (
    get_disk_partitions,
    test_atomic_hardlink,
    create_homelab_directory_tree,
    verify_path_writable,
)
from .netplan_manager import (
    probe_network_interfaces,
    generate_netplan_yaml,
    safe_apply_netplan,
    confirm_netplan_change,
    netplan_change_status,
    backup_netplan_configs,
)
from .env_manager import (
    load_env_file,
    write_env_file,
    update_env_variables,
    sync_all_blueprint_envs,
)
from .system_prober import get_system_snapshot, generate_ai_context_dump, probe_timezone

__all__ = [
    "ETC_DIR",
    "STATE_DIR",
    "APPDATA_DIR",
    "CONFIG_FILE",
    "MANIFEST_FILE",
    "CONTROL_HUB_TOKEN_FILE",
    "SERVICE_USER",
    "module_env_file",
    "module_appdata_dir",
    "is_linux_host",
    "generate_token",
    "write_token_file",
    "read_token_file",
    "load_control_hub_token",
    "extract_token",
    "token_matches",
    "generate_password",
    "generate_api_key",
    "generate_all_secrets",
    "check_port",
    "check_ports_matrix",
    "get_default_ports",
    "get_disk_partitions",
    "test_atomic_hardlink",
    "create_homelab_directory_tree",
    "verify_path_writable",
    "probe_network_interfaces",
    "generate_netplan_yaml",
    "safe_apply_netplan",
    "confirm_netplan_change",
    "netplan_change_status",
    "backup_netplan_configs",
    "load_env_file",
    "write_env_file",
    "update_env_variables",
    "sync_all_blueprint_envs",
    "get_system_snapshot",
    "generate_ai_context_dump",
    "probe_timezone",
]
