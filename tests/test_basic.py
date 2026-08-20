"""Minimal smoke test for Phyn integration."""
import json
from pathlib import Path

import yaml

COMPONENT = Path(__file__).parent.parent / "custom_components" / "phyn"
REPO_ROOT = Path(__file__).parent.parent


def test_manifest_exists():
    """Test that manifest.json exists and is valid."""
    manifest_path = Path(__file__).parent.parent / "custom_components" / "phyn" / "manifest.json"
    
    assert manifest_path.exists(), "manifest.json not found"
    
    with open(manifest_path) as f:
        manifest = json.load(f)
    
    assert manifest["domain"] == "phyn"
    assert manifest["name"] == "Phyn"
    assert "version" in manifest
    assert len(manifest["version"]) > 0


def test_init_file_exists():
    """Test that __init__.py exists."""
    init_path = Path(__file__).parent.parent / "custom_components" / "phyn" / "__init__.py"
    assert init_path.exists(), "__init__.py not found"


def test_strings_file_exists():
    """Test that strings.json exists and is valid."""
    strings_path = Path(__file__).parent.parent / "custom_components" / "phyn" / "strings.json"

    assert strings_path.exists(), "strings.json not found"

    with open(strings_path) as f:
        strings = json.load(f)

    assert "config" in strings


def test_manifest_declares_local_and_push():
    """The manifest reflects the local-access rework."""
    with open(COMPONENT / "manifest.json") as f:
        manifest = json.load(f)

    assert manifest["iot_class"] == "cloud_push"
    dhcp = manifest.get("dhcp", [])
    assert any(m.get("macaddress", "").startswith("28F537") for m in dhcp), (
        "DHCP discovery matcher for the Phyn OUI is missing"
    )


def test_services_yaml_matches_strings():
    """Every service in services.yaml has name/description strings."""
    with open(COMPONENT / "services.yaml") as f:
        services = yaml.safe_load(f)
    with open(COMPONENT / "strings.json") as f:
        strings = json.load(f)

    for service_name, definition in services.items():
        entry = strings.get("services", {}).get(service_name)
        assert entry, f"strings.json is missing service {service_name}"
        assert entry.get("name") and entry.get("description")
        for field in (definition or {}).get("fields", {}):
            assert field in entry.get("fields", {}), (
                f"strings.json is missing field {service_name}.{field}"
            )


def test_blueprints_are_valid():
    """All shipped blueprints parse and have the required metadata."""

    class BlueprintLoader(yaml.SafeLoader):
        """Loader that tolerates HA's !input tag."""

    BlueprintLoader.add_constructor(
        "!input", lambda loader, node: {"__input__": loader.construct_scalar(node)}
    )

    blueprint_dir = REPO_ROOT / "blueprints" / "automation" / "phyn"
    files = sorted(blueprint_dir.glob("*.yaml"))
    assert files, "no blueprints found"
    for path in files:
        with open(path) as f:
            data = yaml.load(f, Loader=BlueprintLoader)
        meta = data.get("blueprint")
        assert meta, f"{path.name}: missing blueprint key"
        assert meta.get("domain") == "automation", path.name
        assert meta.get("name") and meta.get("description"), path.name
        assert meta.get("source_url", "").endswith(path.name), (
            f"{path.name}: source_url must point at this file"
        )
        assert "triggers" in data or "trigger" in data, path.name
        assert "actions" in data or "action" in data, path.name


def test_translations_en_in_sync():
    """translations/en.json must be regenerated from strings.json."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "sync_translations.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
