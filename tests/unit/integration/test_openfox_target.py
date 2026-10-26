"""Unit and integration tests for the OpenFox target."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from apm_cli.core.target_catalog import TARGET_CAPABILITIES, expand_all
from apm_cli.core.target_detection import (
    ALL_CANONICAL_TARGETS,
    VALID_TARGET_VALUES,
    detect_target,
    get_target_description,
    should_compile_agents_md,
    should_compile_claude_md,
)
from apm_cli.integration.agent_integrator import AgentIntegrator
from apm_cli.integration.skill_integrator import SkillIntegrator
from apm_cli.integration.targets import KNOWN_TARGETS
from apm_cli.models.apm_package import (
    APMPackage,
    GitReferenceType,
    PackageInfo,
    ResolvedReference,
)
from apm_cli.utils.yaml_io import loads_frontmatter


def _make_package_info(package_dir: Path, name: str = "test-pkg") -> PackageInfo:
    package = APMPackage(
        name=name,
        version="1.0.0",
        package_path=package_dir,
        source=f"github.com/test/{name}",
    )
    resolved_ref = ResolvedReference(
        original_ref="main",
        ref_type=GitReferenceType.BRANCH,
        resolved_commit="abc123",
        ref_name="main",
    )
    return PackageInfo(
        package=package,
        install_path=package_dir,
        resolved_reference=resolved_ref,
        installed_at=datetime.now().isoformat(),
    )


class TestOpenFoxTargetProfile:
    """Tests for the OpenFox target profile definition."""

    def test_target_capabilities(self) -> None:
        cap = TARGET_CAPABILITIES["openfox"]
        assert cap.name == "openfox"
        assert cap.in_all is True
        assert cap.compile_family == "agents"
        assert cap.primitive_profile == "openfox"
        assert cap.mcp_only is False

    def test_known_targets_profile(self) -> None:
        profile = KNOWN_TARGETS["openfox"]
        assert profile.root_dir == ".openfox"
        assert profile.auto_create is True
        assert profile.detect_by_dir is True
        assert profile.user_supported is False
        assert profile.user_root_dir is None
        assert set(profile.primitives.keys()) == {"skills", "agents"}

    def test_skills_mapping(self) -> None:
        mapping = KNOWN_TARGETS["openfox"].primitives["skills"]
        assert mapping.subdir == "skills"
        assert mapping.extension == "/SKILL.md"
        assert mapping.format_id == "skill_standard"
        assert mapping.deploy_root is None
        assert KNOWN_TARGETS["openfox"].skills_rel_root == ".openfox/skills"

    def test_agents_mapping(self) -> None:
        mapping = KNOWN_TARGETS["openfox"].primitives["agents"]
        assert mapping.subdir == "agents"
        assert mapping.extension == ".agent.md"
        assert mapping.format_id == "openfox_agent"

    def test_membership_in_target_sets(self) -> None:
        assert "openfox" in ALL_CANONICAL_TARGETS
        assert "openfox" in VALID_TARGET_VALUES
        assert "openfox" in expand_all("install")

    def test_no_global_user_scope(self) -> None:
        profile = KNOWN_TARGETS["openfox"]
        assert profile.user_supported is False
        assert profile.for_scope(user_scope=True) is None


class TestOpenFoxTargetDetection:
    """Tests for target detection with OpenFox."""

    def test_detect_by_dir(self, tmp_path: Path) -> None:
        (tmp_path / ".openfox").mkdir()
        target, reason = detect_target(tmp_path)
        assert target == "openfox"
        assert ".openfox/" in reason

    def test_explicit_target_wins(self, tmp_path: Path) -> None:
        target, reason = detect_target(tmp_path, explicit_target="openfox")
        assert target == "openfox"
        assert reason == "explicit --target flag"

    def test_config_target(self, tmp_path: Path) -> None:
        target, reason = detect_target(tmp_path, config_target="openfox")
        assert target == "openfox"
        assert reason == "apm.yml target"

    def test_compilation_routing(self) -> None:
        assert should_compile_agents_md("openfox") is True
        assert should_compile_claude_md("openfox") is False

    def test_description(self) -> None:
        desc = get_target_description("openfox")
        assert "AGENTS.md" in desc
        assert ".openfox/agents/" in desc
        assert ".openfox/skills/" in desc


class TestOpenFoxSkillIntegration:
    """Tests for deploying skills to .openfox/skills/."""

    def test_skill_deployment_path(self, tmp_path: Path) -> None:
        (tmp_path / ".openfox").mkdir()
        pkg_dir = tmp_path / "pkg"
        pkg_dir.mkdir()
        skill_dir = pkg_dir / ".apm" / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: Test skill\n---\n# My Skill\n",
            encoding="utf-8",
        )

        integrator = SkillIntegrator()
        pkg_info = _make_package_info(pkg_dir)
        integrator.integrate_package_skill(
            pkg_info,
            tmp_path,
            targets=[KNOWN_TARGETS["openfox"]],
        )

        deployed = tmp_path / ".openfox" / "skills" / "my-skill" / "SKILL.md"
        assert deployed.exists()
        assert "Test skill" in deployed.read_text(encoding="utf-8")


class TestOpenFoxAgentIntegration:
    """Tests for deploying agents to .openfox/agents/."""

    def test_agent_deployment_with_missing_id_injects_id(self, tmp_path: Path) -> None:
        (tmp_path / ".openfox").mkdir()
        pkg_dir = tmp_path / "pkg"
        pkg_dir.mkdir()
        agent_dir = pkg_dir / ".apm" / "agents"
        agent_dir.mkdir(parents=True)
        (agent_dir / "reviewer.agent.md").write_text(
            "---\nname: reviewer\ndescription: Code reviewer\ntools:\n  - bash\n  - read_file\n---\nReview code.\n",
            encoding="utf-8",
        )

        integrator = AgentIntegrator()
        pkg_info = _make_package_info(pkg_dir)
        result = integrator.integrate_agents_for_target(
            KNOWN_TARGETS["openfox"],
            pkg_info,
            tmp_path,
        )
        assert result.files_integrated == 1

        deployed = tmp_path / ".openfox" / "agents" / "reviewer.agent.md"
        assert deployed.exists()
        post = loads_frontmatter(deployed.read_text(encoding="utf-8"))
        assert post.metadata["id"] == "reviewer"
        assert post.metadata["name"] == "reviewer"
        assert post.metadata["allowedTools"] == ["bash", "read_file"]
        assert "Review code." in post.content

    def test_agent_deployment_preserves_existing_id(self, tmp_path: Path) -> None:
        (tmp_path / ".openfox").mkdir()
        pkg_dir = tmp_path / "pkg"
        pkg_dir.mkdir()
        agent_dir = pkg_dir / ".apm" / "agents"
        agent_dir.mkdir(parents=True)
        (agent_dir / "custom.agent.md").write_text(
            "---\nid: my-special-id\nname: Custom Agent\ndescription: Specialized\n---\nPrompt body.\n",
            encoding="utf-8",
        )

        integrator = AgentIntegrator()
        pkg_info = _make_package_info(pkg_dir)
        integrator.integrate_agents_for_target(
            KNOWN_TARGETS["openfox"],
            pkg_info,
            tmp_path,
        )

        deployed = tmp_path / ".openfox" / "agents" / "custom.agent.md"
        assert deployed.exists()
        post = loads_frontmatter(deployed.read_text(encoding="utf-8"))
        assert post.metadata["id"] == "my-special-id"
        assert post.metadata["name"] == "Custom Agent"

    def test_agent_plain_md_extension_becomes_agent_md(self, tmp_path: Path) -> None:
        (tmp_path / ".openfox").mkdir()
        pkg_dir = tmp_path / "pkg"
        pkg_dir.mkdir()
        agent_dir = pkg_dir / ".apm" / "agents"
        agent_dir.mkdir(parents=True)
        (agent_dir / "helper.md").write_text(
            "---\ndescription: General helper\n---\nHelp the user.\n",
            encoding="utf-8",
        )

        integrator = AgentIntegrator()
        pkg_info = _make_package_info(pkg_dir)
        integrator.integrate_agents_for_target(
            KNOWN_TARGETS["openfox"],
            pkg_info,
            tmp_path,
        )

        deployed = tmp_path / ".openfox" / "agents" / "helper.agent.md"
        assert deployed.exists()
        raw = deployed.read_text(encoding="utf-8")
        assert raw.endswith("\n")
        post = loads_frontmatter(raw)
        assert post.metadata["id"] == "helper"

    def test_agent_frontmatter_preserves_order_and_warns_on_malformed(self, tmp_path: Path) -> None:
        (tmp_path / ".openfox").mkdir()
        pkg_dir = tmp_path / "pkg"
        pkg_dir.mkdir()
        agent_dir = pkg_dir / ".apm" / "agents"
        agent_dir.mkdir(parents=True)
        # Malformed frontmatter
        (agent_dir / "bad.agent.md").write_text(
            "---\n: bad yaml\n---\nBroken frontmatter.\n",
            encoding="utf-8",
        )

        from apm_cli.utils.diagnostics import DiagnosticCollector

        diagnostics = DiagnosticCollector()
        integrator = AgentIntegrator()
        pkg_info = _make_package_info(pkg_dir)
        integrator.integrate_agents_for_target(
            KNOWN_TARGETS["openfox"],
            pkg_info,
            tmp_path,
            diagnostics=diagnostics,
        )

        deployed = tmp_path / ".openfox" / "agents" / "bad.agent.md"
        assert deployed.exists()
        assert deployed.read_text(encoding="utf-8").endswith("\n")
        # Check that warning diagnostic was emitted
        warnings = diagnostics.by_category().get("warning", [])
        assert any("OpenFox agent" in w.message and "bad.agent.md" in w.message for w in warnings)

    def test_hidden_trees_and_virtual_roots_include_openfox(self) -> None:
        from apm_cli.compilation.context_optimizer import PLACEMENT_HIDDEN_TOOL_TREES
        from apm_cli.models.dependency.host_virtual import _HOST_QUALIFIED_VIRTUAL_ROOTS

        assert ".openfox" in PLACEMENT_HIDDEN_TOOL_TREES
        assert ".openfox" in _HOST_QUALIFIED_VIRTUAL_ROOTS
