"""Repair missing FastAPI router registration without replacing app."""

from __future__ import annotations

import ast
import importlib
import shutil
from datetime import datetime
from pathlib import Path

MAIN = Path("app/main.py")

ROUTERS = {
    "shipments": "app.api.shipments",
    "exceptions": "app.api.exceptions",
    "detection": "app.api.detection",
}

source = MAIN.read_text()
tree = ast.parse(source)

if not any(
    isinstance(node, ast.Assign)
    and any(
        isinstance(target, ast.Name) and target.id == "app"
        for target in node.targets
    )
    for node in tree.body
):
    raise RuntimeError("Could not locate FastAPI app assignment.")

for name, module_path in ROUTERS.items():
    module_file = Path(module_path.replace(".", "/") + ".py")
    if not module_file.is_file():
        raise RuntimeError(f"Missing API file: {module_file}")

    module = importlib.import_module(module_path)
    if not hasattr(module, "router"):
        raise RuntimeError(f"Missing router in {module_path}")

    print(f"PASS: {name} router importable")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = Path(f"backups/main_before_router_fix_{stamp}.py")
shutil.copy2(MAIN, backup)
print(f"Backup: {backup}")

marker = "# DISPATCHRESOLVE_ROUTER_REGISTRATION_V1"

if marker not in source:
    source += f"""

{marker}
def _register_dispatchresolve_routers() -> None:
    from app.api.shipments import router as shipments_router
    from app.api.exceptions import router as exceptions_router
    from app.api.detection import router as detection_router

    existing = {{
        (route.path, tuple(sorted(getattr(route, "methods", ()))))
        for route in app.routes
    }}

    for router in (
        shipments_router,
        exceptions_router,
        detection_router,
    ):
        signatures = {{
            (
                route.path,
                tuple(sorted(getattr(route, "methods", ()))),
            )
            for route in router.routes
        }}

        if not signatures.issubset(existing):
            if signatures & existing:
                raise RuntimeError(
                    "Partial router registration detected. "
                    "Inspect app/main.py before proceeding."
                )

            app.include_router(router)
            existing.update(signatures)


_register_dispatchresolve_routers()
"""
    MAIN.write_text(source)
    print("PASS: Router registration installed")
else:
    print("PASS: Router registration already installed")
