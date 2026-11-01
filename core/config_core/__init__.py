"""
Homelab Blueprint - Modular Configuration Engine (config_core)
Shared core for Initial Setup Wizard & Control Hub Live Settings
"""

from .secrets_generator import generate_password, generate_api_key, generate_all_secrets
from .port_manager import check_port, check_ports_matrix, get_default_ports
from .storage_manager import (
    get_disk_partitions,
    test_atomic_hardlink,
    create_homelab_directory_tree,
    verify_path_writable
)
from .netplan_manager import (
    probe_network_interfaces,
    generate_netplan_yaml,
    safe_apply_netplan,
    backup_netplan_configs
)
from .env_manager import (
    load_env_file,
    write_env_file,
    update_env_variables,
    sync_all_blueprint_envs
)
from .system_prober import get_system_snapshot, generate_ai_context_dump
from .service_deployer import deploy_homelab_stack

__all__ = [
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
    "backup_netplan_configs",
    "load_env_file",
    "write_env_file",
    "update_env_variables",
    "sync_all_blueprint_envs",
    "get_system_snapshot",
    "generate_ai_context_dump",
    "deploy_homelab_stack",
]
