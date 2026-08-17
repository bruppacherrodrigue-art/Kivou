"""L'isolation du vérificateur commercial (SPEC-009B §1).

SPEC-009A a produit une infrastructure expérimentale qui n'a pas passé ses gates.
Elle est conservée parce qu'elle reste informative — mais conserver du code mort
n'est sûr que si son inertie est vérifiée, pas supposée.

Ces tests prouvent l'isolation dans les deux sens : rien du produit ne l'importe,
et elle n'importe aucun moteur. Le jour où quelqu'un la branchera par inadvertance
à un feed client, c'est ici que cela cassera.
"""

from __future__ import annotations

import ast
import pathlib

SRC = pathlib.Path("src/signals")
VERIFICATION = SRC / "verification"

#: Les paquets qui constituent le pipeline produit. Aucun ne doit connaître le
#: vérificateur, et le vérificateur ne doit connaître aucun d'eux.
ENGINE_PACKAGES = (
    "matching",
    "needs",
    "understanding",
    "resolution",
    "connectors",
    "domain",
    "documents",
)

#: Le harnais de recherche et l'adaptateur ont le droit de composer les deux
#: mondes : ce sont des points d'entrée d'expérience, pas du runtime produit.
COMPOSITION_ROOTS = (
    "src/signals/research/verifier_dev.py",
    "src/signals/verification/openrouter.py",
)


def _imports(path: pathlib.Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


class TestNothingInProductionImportsTheVerifier:
    def test_no_engine_package_imports_it(self) -> None:
        """§1 — aucun runtime produit ne l'importe."""
        for package in ENGINE_PACKAGES:
            for path in (SRC / package).rglob("*.py"):
                for module in _imports(path):
                    assert "signals.verification" not in module, f"{path} importe le vérificateur"

    def test_no_engine_package_imports_the_research_harness(self) -> None:
        for package in ENGINE_PACKAGES:
            for path in (SRC / package).rglob("*.py"):
                for module in _imports(path):
                    assert "verifier_dev" not in module, f"{path} importe le harnais DEV"

    def test_only_the_declared_composition_roots_bridge_the_two_worlds(self) -> None:
        """Un pont non déclaré serait un branchement en production qui s'ignore."""
        bridges = []
        for path in SRC.rglob("*.py"):
            modules = _imports(path)
            bridges_verification = any("signals.verification" in m for m in modules)
            bridges_research = any("verifier_dev" in m for m in modules)
            if (bridges_verification or bridges_research) and not str(path).startswith(
                "src/signals/verification/"
            ):
                bridges.append(str(path))
        assert sorted(bridges) == ["src/signals/research/verifier_dev.py"]


class TestTheVerifierDependsOnNoEngine:
    def test_it_imports_no_engine_package(self) -> None:
        """L'inverse compte autant : un vérificateur couplé à un moteur le fige."""
        for path in VERIFICATION.glob("*.py"):
            if str(path) in COMPOSITION_ROOTS:
                continue
            for module in _imports(path):
                for package in ENGINE_PACKAGES:
                    assert f"signals.{package}" not in module, f"{path} importe signals.{package}"


class TestNoProductionActivationPathExists:
    def test_no_feature_flag_can_enable_it(self) -> None:
        """§1 — « ne crée pas un feature flag de production ».

        On cherche un *mécanisme* d'activation, pas un mot : une constante de
        module dont le nom parle d'activation. La prose du docstring dit
        « NOT PRODUCTION ENABLED », ce qui est l'inverse d'un interrupteur.
        """
        for path in VERIFICATION.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:
                if not isinstance(node, ast.Assign):
                    continue
                for target in node.targets:
                    if not isinstance(target, ast.Name):
                        continue
                    name = target.id.upper()
                    if "ENABLE" in name or "ACTIVAT" in name:
                        raise AssertionError(f"{path} expose {target.id}, un interrupteur")

    def test_the_package_declares_its_experimental_status(self) -> None:
        """Un lecteur qui ouvre le paquet doit apprendre son statut en trois lignes."""
        docstring = (VERIFICATION / "__init__.py").read_text(encoding="utf-8")
        assert "EXPERIMENTAL" in docstring
        assert "NOT PRODUCTION ENABLED" in docstring
        assert "GENERALIST FILTER FAILED DEV GATES" in docstring
