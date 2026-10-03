"""Small, explicit SmartConfig capability catalog.

Recipes are intentionally configuration-level claims.  They do not certify
firmware, permissions, packaging, or runtime functionality.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CapabilityRecipe:
    id: str
    title: str
    scope: str
    condition: dict[str, Any]
    exclusions: tuple[str, ...]


RECIPES: dict[str, CapabilityRecipe] = {
    "wireguard": CapabilityRecipe(
        "wireguard", "WireGuard interface support", "kernel WireGuard provider",
        {"symbol": "WIREGUARD", "allowed": ["y", "m"]},
        ("userspace WireGuard is outside this recipe",),
    ),
    "kvm-host": CapabilityRecipe(
        "kvm-host", "KVM host support", "x86 KVM host provider",
        {"all": [{"symbol": "KVM", "allowed": ["y", "m"]}, {"any": [
            {"symbol": "KVM_INTEL", "allowed": ["y", "m"]},
            {"symbol": "KVM_AMD", "allowed": ["y", "m"]},
        ]}]},
        ("CPU virtualization firmware and permissions are not checked",),
    ),
    "overlayfs": CapabilityRecipe(
        "overlayfs", "OverlayFS mount support", "mounting OverlayFS",
        {"symbol": "OVERLAY_FS", "allowed": ["y", "m"]},
        ("container networking and rootless policy are excluded",),
    ),
    "tun-tap": CapabilityRecipe(
        "tun-tap", "TUN/TAP interface support", "creating TUN/TAP interfaces",
        {"symbol": "TUN", "allowed": ["y", "m"]},
        ("device permissions and userspace daemon behavior are excluded",),
    ),
    "usb-mass-storage": CapabilityRecipe(
        "usb-mass-storage", "USB mass storage", "USB storage with a declared filesystem",
        {"all": [{"symbol": "USB_STORAGE", "allowed": ["y", "m"]}, {"any": [
            {"symbol": "EXT4_FS", "allowed": ["y", "m"]},
            {"symbol": "VFAT_FS", "allowed": ["y", "m"]},
            {"symbol": "XFS_FS", "allowed": ["y", "m"]},
        ]}]},
        ("filesystem choice is conservative and must be edited for other filesystems",),
    ),
    "root-storage": CapabilityRecipe(
        "root-storage", "Configured root storage", "plain or encrypted root filesystem",
        {"any": [
            {"symbol": "EXT4_FS", "allowed": ["y", "m"]},
            {"symbol": "XFS_FS", "allowed": ["y", "m"]},
            {"symbol": "BTRFS_FS", "allowed": ["y", "m"]},
        ]},
        ("the boot chain, initramfs contents, encryption, and layered storage require separate validation",),
    ),
}


def recipe_requirements(names: list[str]) -> list[dict[str, Any]]:
    """Return versioned, user-editable requirement records."""
    unknown = sorted(set(names) - RECIPES.keys())
    if unknown:
        raise ValueError(f"unknown capabilities: {', '.join(unknown)}")
    return [
        {"id": recipe.id, "title": recipe.title, "scope": recipe.scope,
         "origin": "user", "strength": "required", "recipe_version": "1",
         "condition": recipe.condition, "exclusions": list(recipe.exclusions)}
        for recipe in (RECIPES[name] for name in names)
    ]


def validate_recipes() -> list[str]:
    errors: list[str] = []
    for key, recipe in RECIPES.items():
        if key != recipe.id or not recipe.title or not recipe.scope:
            errors.append(f"{key}: missing stable metadata")
        if not isinstance(recipe.condition, dict):
            errors.append(f"{key}: condition is not an object")
    return errors
