"""Consolidate business API registration safely."""

import ast
import shutil
from datetime import datetime
from pathlib import Path

MAIN = Path("app/main.py")

START = "# DISPATCHRESOLVE_ROUTER_REGISTRATION_V1"
END = "# DISPATCHRESOLVE_AUTH_ROUTER_V1"
OLD_PROTECTION = "# DISPATCHRESOLVE_PROTECTED_ROUTERS_V1"
NEW_PROTECTION = "# DISPATCHRESOLVE_AUTH_BEFORE_REGISTRATION_V1"

source = MAIN.read_text()

if NEW_PROTECTION in source:
    print("SKIP: New authentication registration already present")
    raise SystemExit(0)

required = (
    START,
    END,
    OLD_PROTECTION,
    "app.include_router(shipments_router)",
)

missing = [marker for marker in required if marker not in source]

if missing:
    raise SystemExit(
        f"STOP: Unexpected main.py structure. Missing markers: {missing}. No changes made."
    )

if not source.index(START) < source.index(END):
    raise SystemExit("STOP: Unexpected registration order")

backup = Path("backups/main_before_sprint1_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".py")

backup.parent.mkdir(exist_ok=True)
shutil.copy2(MAIN, backup)

# Remove the second business-router registration.
source = source[: source.index(START)] + source[source.index(END) :]

# Remove the old late authentication mutation.
source = source[: source.index(OLD_PROTECTION)]

protection = """
# DISPATCHRESOLVE_AUTH_BEFORE_REGISTRATION_V1
def _protect_business_routers() -> None:
    from fastapi import Depends

    from app.api.dependencies import get_auth_context

    for business_router in (
        shipments_router,
        exceptions_router,
        detection_router,
    ):
        for route in business_router.routes:
            if not hasattr(route, "dependencies"):
                continue

            if not any(
                getattr(dep, "dependency", None)
                is get_auth_context
                for dep in route.dependencies
            ):
                route.dependencies.append(
                    Depends(get_auth_context)
                )


_protect_business_routers()


"""

source = source.replace(
    "app.include_router(shipments_router)",
    protection + "app.include_router(shipments_router)",
    1,
)

ast.parse(source)
MAIN.write_text(source)

print("PASS: Duplicate business-router registration removed")
print("PASS: Authentication installed before registration")
print("BACKUP:", backup)
