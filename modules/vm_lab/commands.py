"""Command-to-backend argument builders for vm_lab CLI."""

from __future__ import annotations

import argparse
from typing import Callable


def _add_common_flags(p: argparse.ArgumentParser, *, allow_apply: bool = False, allow_manifest_root: bool = True) -> None:
    if allow_manifest_root:
        p.add_argument("-mr", "--manifest-root", help="Override vm_lab ownership manifest root.")
    if allow_apply:
        p.add_argument("-a", "--apply", action="store_true", help="Authorize mutating execution (default is dry-run).")
    p.add_argument("-j", "--json", action="store_true", help="Emit single-document JSON output.")


def _append_common(ps_args: list[str], ns: argparse.Namespace) -> None:
    if getattr(ns, "manifest_root", None):
        ps_args.extend(["-ManifestRoot", ns.manifest_root])
    if getattr(ns, "apply", False):
        ps_args.append("-Apply")
    if getattr(ns, "json", False):
        ps_args.append("-Json")


def _build_simple(op: str, *, positional_name: bool = True) -> Callable[[argparse.Namespace], tuple[list[str], bool]]:
    def _builder(ns: argparse.Namespace) -> tuple[list[str], bool]:
        ps = ["-o", op]
        if positional_name and getattr(ns, "name", None):
            ps.extend(["-Name", ns.name])
        if getattr(ns, "vm_root", None):
            ps.extend(["-VmRoot", ns.vm_root])
        if getattr(ns, "template", None):
            ps.extend(["-TemplateName", ns.template])
        if getattr(ns, "iso", None):
            ps.extend(["-IsoPath", ns.iso])
        if getattr(ns, "switch", None):
            ps.extend(["-SwitchName", ns.switch])
        if getattr(ns, "config", None):
            ps.extend(["-ConfigPath", ns.config])
        if getattr(ns, "min_reserve_bytes", None) is not None:
            ps.extend(["-MinReserveBytes", str(ns.min_reserve_bytes)])
        if getattr(ns, "shutdown_timeout", None) is not None:
            ps.extend(["-ShutdownTimeoutSeconds", str(ns.shutdown_timeout)])
        if getattr(ns, "start", False):
            ps.append("-Start")
        if getattr(ns, "connect", False):
            ps.append("-Connect")
        _append_common(ps, ns)
        return ps, False

    return _builder


def _build_list(ns: argparse.Namespace) -> tuple[list[str], bool]:
    ps = ["-o", "list"]
    if ns.owned_only:
        ps.append("-OwnedOnly")
    _append_common(ps, ns)
    return ps, False


def _build_template_info(ns: argparse.Namespace) -> tuple[list[str], bool]:
    ps = ["-o", "template-info", "-TemplateName", ns.template]
    _append_common(ps, ns)
    return ps, False


def _build_wizard(ns: argparse.Namespace) -> tuple[list[str], bool]:
    ps = ["-o", "wizard"]
    if getattr(ns, "manifest_root", None):
        ps.extend(["-ManifestRoot", ns.manifest_root])
    return ps, True


def _build_unattend(ns: argparse.Namespace) -> tuple[list[str], bool]:
    ps = ["-o", "unattend-xml", "-OutputPath", ns.output_path, "-Locale", ns.locale, "-KeyboardLayout", ns.keyboard_layout]
    if ns.image_edition:
        ps.extend(["-ImageEdition", ns.image_edition])
    if ns.overwrite:
        ps.append("-Overwrite")
    _append_common(ps, ns)
    return ps, False


def _build_guest_status(ns: argparse.Namespace) -> tuple[list[str], bool]:
    ps = ["-o", "guest-status", "-Name", ns.name]
    if ns.prompt_credential:
        ps.append("-PromptCredential")
    _append_common(ps, ns)
    return ps, bool(ns.prompt_credential)


def _build_guest_copy(ns: argparse.Namespace) -> tuple[list[str], bool]:
    ps = ["-o", "guest-copy", "-Name", ns.name, "-SourcePath", ns.source, "-DestinationPath", ns.destination, "-Direction", ns.direction]
    if ns.overwrite:
        ps.append("-Overwrite")
    if ns.prompt_credential:
        ps.append("-PromptCredential")
    _append_common(ps, ns)
    return ps, bool(ns.prompt_credential)


def _build_guest_bootstrap(ns: argparse.Namespace) -> tuple[list[str], bool]:
    ps = ["-o", "guest-bootstrap", "-Name", ns.name, "-GuestProfile", ns.profile, "-VenvPath", ns.venv_path]
    if ns.installer_path:
        ps.extend(["-InstallerPath", ns.installer_path])
    if ns.expected_installer_sha256:
        ps.extend(["-ExpectedInstallerSha256", ns.expected_installer_sha256])
    if ns.python_path:
        ps.extend(["-PythonPath", ns.python_path])
    if ns.wheelhouse_path:
        ps.extend(["-WheelhousePath", ns.wheelhouse_path])
    if ns.requirements_path:
        ps.extend(["-RequirementsPath", ns.requirements_path])
    if ns.packages:
        ps.extend(["-Packages", *ns.packages])
    if ns.offline:
        ps.append("-Offline")
    if ns.allow_online_install:
        ps.append("-AllowOnlineInstall")
    if ns.prompt_credential:
        ps.append("-PromptCredential")
    _append_common(ps, ns)
    return ps, bool(ns.prompt_credential)


def _build_guest_verify(ns: argparse.Namespace) -> tuple[list[str], bool]:
    ps = ["-o", "guest-verify", "-Name", ns.name, "-GuestProfile", ns.profile, "-VenvPath", ns.venv_path]
    if ns.require_guest_verified:
        ps.append("-RequireGuestVerified")
    if ns.prompt_credential:
        ps.append("-PromptCredential")
    _append_common(ps, ns)
    return ps, bool(ns.prompt_credential)


def _build_guest_exec(op: str) -> Callable[[argparse.Namespace], tuple[list[str], bool]]:
    def _builder(ns: argparse.Namespace) -> tuple[list[str], bool]:
        ps = ["-o", op, "-Name", ns.name, "-ExecutablePath", ns.executable, "-WorkingDirectory", ns.working_directory]
        extra = [a for a in (ns.exec_args or []) if a != "--"]
        if extra:
            ps.extend(["-ArgumentList", *extra])
        if getattr(ns, "expected_sha256", None):
            ps.extend(["-ExpectedSha256", ns.expected_sha256])
        if getattr(ns, "operation_id", None):
            ps.extend(["-OperationId", ns.operation_id])
        if getattr(ns, "authorize_guest_exec", False):
            ps.append("-AuthorizeGuestExec")
        if getattr(ns, "prompt_credential", False):
            ps.append("-PromptCredential")
        _append_common(ps, ns)
        return ps, bool(getattr(ns, "prompt_credential", False))

    return _builder


def _build_artifact(op: str) -> Callable[[argparse.Namespace], tuple[list[str], bool]]:
    def _builder(ns: argparse.Namespace) -> tuple[list[str], bool]:
        if not getattr(ns, "manifest", None) and not getattr(ns, "destination", None):
            raise ValueError("Either --manifest or --destination is required for artifact operations.")
        ps = ["-o", op, "-Name", ns.name, "-SourcePath", ns.source]
        if getattr(ns, "manifest", None):
            ps.extend(["-ArtifactManifestPath", ns.manifest])
        if getattr(ns, "destination", None):
            ps.extend(["-DestinationPath", ns.destination])
        if getattr(ns, "operation_id", None):
            ps.extend(["-OperationId", ns.operation_id])
        if getattr(ns, "authorize_guest_mutation", False):
            ps.append("-AuthorizeGuestMutation")
        if getattr(ns, "prompt_credential", False):
            ps.append("-PromptCredential")
        _append_common(ps, ns)
        return ps, bool(getattr(ns, "prompt_credential", False))

    return _builder


def _build_evidence(op: str) -> Callable[[argparse.Namespace], tuple[list[str], bool]]:
    def _builder(ns: argparse.Namespace) -> tuple[list[str], bool]:
        ps = ["-o", op, "-Name", ns.name, "-GuestRoots", *ns.guest_roots, "-EvidenceRoot", ns.evidence_root]
        if getattr(ns, "operation_id", None):
            ps.extend(["-OperationId", ns.operation_id])
        if getattr(ns, "prompt_credential", False):
            ps.append("-PromptCredential")
        _append_common(ps, ns)
        return ps, bool(getattr(ns, "prompt_credential", False))

    return _builder


def _build_checkpoint(op: str) -> Callable[[argparse.Namespace], tuple[list[str], bool]]:
    def _builder(ns: argparse.Namespace) -> tuple[list[str], bool]:
        ps = ["-o", op, "-Name", ns.name]
        if getattr(ns, "checkpoint_name", None):
            ps.extend(["-CheckpointName", ns.checkpoint_name])
        if getattr(ns, "restart_after", False):
            ps.append("-RestartAfter")
        if getattr(ns, "authorize_vm_lifecycle", False):
            ps.append("-AuthorizeVmLifecycle")
        if getattr(ns, "prompt_credential", False):
            ps.append("-PromptCredential")
        _append_common(ps, ns)
        return ps, bool(getattr(ns, "prompt_credential", False))

    return _builder


def _build_workflow(op: str) -> Callable[[argparse.Namespace], tuple[list[str], bool]]:
    def _builder(ns: argparse.Namespace) -> tuple[list[str], bool]:
        ps = ["-o", op]
        if getattr(ns, "file", None):
            ps.extend(["-WorkflowPath", ns.file])
        if getattr(ns, "operation_id", None):
            ps.extend(["-OperationId", ns.operation_id])
        if getattr(ns, "operation_root", None):
            ps.extend(["-OperationRoot", ns.operation_root])
        if getattr(ns, "authorize_host_mutation", False):
            ps.append("-AuthorizeHostMutation")
        if getattr(ns, "authorize_vm_lifecycle", False):
            ps.append("-AuthorizeVmLifecycle")
        if getattr(ns, "authorize_guest_mutation", False):
            ps.append("-AuthorizeGuestMutation")
        if getattr(ns, "authorize_guest_exec", False):
            ps.append("-AuthorizeGuestExec")
        if getattr(ns, "authorize_elevation", False):
            ps.append("-AuthorizeElevation")
        if getattr(ns, "prompt_credential", False):
            ps.append("-PromptCredential")
        _append_common(ps, ns)
        return ps, bool(getattr(ns, "prompt_credential", False))

    return _builder


def register_commands(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register all Phase 2 CLI subcommands and nested groups."""
    p_doc = sub.add_parser("doctor", help="Check host Hyper-V and stale lock health.")
    p_doc.set_defaults(_builder=_build_simple("doctor", positional_name=False))
    _add_common_flags(p_doc, allow_manifest_root=False)

    p_list = sub.add_parser("list", help="List Hyper-V VMs.")
    p_list.add_argument("-oo", "--owned-only", action="store_true", help="Show only vm_lab-owned VMs.")
    p_list.set_defaults(_builder=_build_list)
    _add_common_flags(p_list)

    p_insp = sub.add_parser("inspect", aliases=["status"], help="Inspect VM status and ownership.")
    p_insp.add_argument("name", help="VM name.")
    p_insp.set_defaults(_builder=_build_simple("status"))
    _add_common_flags(p_insp)

    p_plan = sub.add_parser("plan", help="Plan VM creation (dry-run).")
    p_plan.add_argument("name", help="Target VM name.")
    p_plan.add_argument("-t", "--template", default="windows11-h4", help="Template name.")
    p_plan.add_argument("-r", "--vm-root", help="VM storage root.")
    p_plan.add_argument("-i", "--iso", help="ISO path.")
    p_plan.add_argument("-s", "--switch", help="Virtual switch name.")
    p_plan.add_argument("-c", "--config", help="JSON config path.")
    p_plan.set_defaults(_builder=_build_simple("plan"))
    _add_common_flags(p_plan)

    p_create = sub.add_parser("create", help="Create a Generation 2 Hyper-V VM.")
    p_create.add_argument("name", help="Target VM name.")
    p_create.add_argument("-t", "--template", default="windows11-h4", help="Template name.")
    p_create.add_argument("-r", "--vm-root", help="VM storage root.")
    p_create.add_argument("-i", "--iso", help="ISO path.")
    p_create.add_argument("-s", "--switch", help="Virtual switch name.")
    p_create.add_argument("-c", "--config", help="JSON config path.")
    p_create.set_defaults(_builder=_build_simple("create"))
    _add_common_flags(p_create, allow_apply=True)

    p_start = sub.add_parser("start", help="Start an owned VM.")
    p_start.add_argument("name", help="VM name.")
    p_start.add_argument("-rb", "--min-reserve-bytes", type=int, help="Minimum free host RAM reserve in bytes.")
    p_start.set_defaults(_builder=_build_simple("start"))
    _add_common_flags(p_start, allow_apply=True)

    p_stop = sub.add_parser("stop", help="Gracefully stop an owned VM.")
    p_stop.add_argument("name", help="VM name.")
    p_stop.add_argument("--shutdown-timeout", type=int, help="Graceful shutdown timeout in seconds.")
    p_stop.set_defaults(_builder=_build_simple("stop"))
    _add_common_flags(p_stop, allow_apply=True)

    p_conn = sub.add_parser("connect", help="Open VMConnect for an owned VM.")
    p_conn.add_argument("name", help="VM name.")
    p_conn.add_argument("--start", action="store_true", help="Start VM before connecting if Off.")
    p_conn.set_defaults(_builder=_build_simple("connect"))
    _add_common_flags(p_conn, allow_apply=True)

    p_sc = sub.add_parser("start-connect", help="Start an owned VM and open VMConnect.")
    p_sc.add_argument("name", help="VM name.")
    p_sc.set_defaults(_builder=_build_simple("start-connect"))
    _add_common_flags(p_sc, allow_apply=True)

    p_qs = sub.add_parser("quickstart", help="Plan or provision a VM from template.")
    p_qs.add_argument("name", help="VM name.")
    p_qs.add_argument("-t", "--template", default="windows11-dev", help="Template name.")
    p_qs.add_argument("-r", "--vm-root", help="VM storage root.")
    p_qs.add_argument("-i", "--iso", help="ISO path.")
    p_qs.add_argument("--start", action="store_true", help="Start VM after creation.")
    p_qs.add_argument("--connect", action="store_true", help="Open VMConnect.")
    p_qs.set_defaults(_builder=_build_simple("quickstart"))
    _add_common_flags(p_qs, allow_apply=True)

    p_wiz = sub.add_parser("wizard", help="Run interactive VM setup wizard.")
    p_wiz.add_argument("-mr", "--manifest-root", help="Override vm_lab ownership manifest root.")
    p_wiz.set_defaults(_builder=_build_wizard)

    p_tpls = sub.add_parser("templates", help="List built-in VM templates.")
    p_tpls.set_defaults(_builder=_build_simple("templates", positional_name=False))
    _add_common_flags(p_tpls, allow_manifest_root=False)

    p_tinfo = sub.add_parser("template-info", help="Show details for a built-in template.")
    p_tinfo.add_argument("template", help="Template name.")
    p_tinfo.set_defaults(_builder=_build_template_info)
    _add_common_flags(p_tinfo, allow_manifest_root=False)

    p_rec = sub.add_parser("recovery-plan", help="Inspect partial artifacts and recovery steps for a VM.")
    p_rec.add_argument("name", help="VM name.")
    p_rec.add_argument("-r", "--vm-root", help="VM storage root.")
    p_rec.set_defaults(_builder=_build_simple("recovery-plan"))
    _add_common_flags(p_rec)

    # boot group
    p_boot = sub.add_parser("boot", help="Firmware and boot diagnostics.")
    sub_boot = p_boot.add_subparsers(dest="boot_cmd", metavar="<action>", required=True)
    p_bi = sub_boot.add_parser("inspect", help="Inspect UEFI firmware boot order and DVD state.")
    p_bi.add_argument("name", help="VM name.")
    p_bi.set_defaults(_builder=_build_simple("boot-diagnostics"))
    _add_common_flags(p_bi)

    # setup group
    p_setup = sub.add_parser("setup", help="Windows Setup and answer-media helpers.")
    sub_setup = p_setup.add_subparsers(dest="setup_cmd", metavar="<action>", required=True)
    p_ans = sub_setup.add_parser("answer-media", help="Generate password-free Autounattend.xml.")
    p_ans.add_argument("output_path", help="Destination Autounattend.xml path.")
    p_ans.add_argument("--locale", default="en-US")
    p_ans.add_argument("--keyboard-layout", default="en-US")
    p_ans.add_argument("--image-edition", help="Optional Windows edition.")
    p_ans.add_argument("--overwrite", action="store_true")
    p_ans.set_defaults(_builder=_build_unattend)
    _add_common_flags(p_ans, allow_apply=True, allow_manifest_root=False)

    # guest group
    p_guest = sub.add_parser("guest", help="PowerShell Direct guest inspection, bootstrap, and execution.")
    sub_guest = p_guest.add_subparsers(dest="guest_cmd", metavar="<action>", required=True)

    p_gs = sub_guest.add_parser("status", help="Check guest PowerShell Direct readiness.")
    p_gs.add_argument("name", help="VM name.")
    p_gs.add_argument("--prompt-credential", action="store_true")
    p_gs.set_defaults(_builder=_build_guest_status)
    _add_common_flags(p_gs)

    p_gc = sub_guest.add_parser("copy", help="Copy verified file/directory to or from guest.")
    p_gc.add_argument("name", help="VM name.")
    p_gc.add_argument("--source", required=True)
    p_gc.add_argument("--destination", required=True)
    p_gc.add_argument("--direction", choices=["ToGuest", "FromGuest"], default="ToGuest")
    p_gc.add_argument("--overwrite", action="store_true")
    p_gc.add_argument("--prompt-credential", action="store_true")
    p_gc.set_defaults(_builder=_build_guest_copy)
    _add_common_flags(p_gc, allow_apply=True)

    p_gb = sub_guest.add_parser("bootstrap", help="Bootstrap guest tools/venv.")
    p_gb.add_argument("name", help="VM name.")
    p_gb.add_argument("--profile", default="windows-minimal")
    p_gb.add_argument("--installer-path")
    p_gb.add_argument("--expected-installer-sha256")
    p_gb.add_argument("--python-path")
    p_gb.add_argument("--wheelhouse-path")
    p_gb.add_argument("--requirements-path")
    p_gb.add_argument("--packages", nargs="+")
    p_gb.add_argument("--venv-path", default=r"C:\venvs\dev")
    p_gb.add_argument("--offline", action="store_true")
    p_gb.add_argument("--allow-online-install", action="store_true")
    p_gb.add_argument("--prompt-credential", action="store_true")
    p_gb.set_defaults(_builder=_build_guest_bootstrap)
    _add_common_flags(p_gb, allow_apply=True)

    p_gv = sub_guest.add_parser("verify", help="Verify guest bootstrap profile.")
    p_gv.add_argument("name", help="VM name.")
    p_gv.add_argument("--profile", default="windows-minimal")
    p_gv.add_argument("--venv-path", default=r"C:\venvs\dev")
    p_gv.add_argument("--require-guest-verified", action="store_true")
    p_gv.add_argument("--prompt-credential", action="store_true")
    p_gv.set_defaults(_builder=_build_guest_verify)
    _add_common_flags(p_gv)

    for sub_name, op in (("command-plan", "guest-command-plan"), ("exec", "guest-exec")):
        p_ge = sub_guest.add_parser(sub_name, help=f"Run {op} on guest.")
        p_ge.add_argument("name", help="VM name.")
        p_ge.add_argument("--executable", required=True, help="Guest executable path.")
        p_ge.add_argument("-w", "--working-directory", default=r"C:\Windows\Temp")
        p_ge.add_argument("--expected-sha256")
        p_ge.add_argument("-op", "--operation-id")
        if op == "guest-exec":
            p_ge.add_argument("--authorize-guest-exec", action="store_true")
            p_ge.add_argument("--prompt-credential", action="store_true")
        p_ge.add_argument("exec_args", nargs="*", help="Arguments (or pass after --).")
        p_ge.set_defaults(_builder=_build_guest_exec(op))
        _add_common_flags(p_ge, allow_apply=(op == "guest-exec"))

    # artifact group
    p_art = sub.add_parser("artifact", help="Trusted artifact manifest planning and deployment.")
    sub_art = p_art.add_subparsers(dest="artifact_cmd", metavar="<action>", required=True)
    for sub_name, op in (("plan", "artifact-plan"), ("deploy", "artifact-deploy")):
        p_a = sub_art.add_parser(sub_name, help=f"Run {op}.")
        p_a.add_argument("name", help="VM name.")
        p_a.add_argument("--source", required=True, help="Host source directory containing artifacts.")
        p_a.add_argument("--manifest", help="Trusted artifact manifest JSON path.")
        p_a.add_argument("--destination", help="Guest destination directory (used when --manifest is omitted).")
        if op == "artifact-deploy":
            p_a.add_argument("-op", "--operation-id")
            p_a.add_argument("--authorize-guest-mutation", action="store_true")
            p_a.add_argument("--prompt-credential", action="store_true")
        p_a.set_defaults(_builder=_build_artifact(op))
        _add_common_flags(p_a, allow_apply=(op == "artifact-deploy"))

    # evidence group
    p_ev = sub.add_parser("evidence", help="Guest evidence planning and collection.")
    sub_ev = p_ev.add_subparsers(dest="evidence_cmd", metavar="<action>", required=True)
    for sub_name, op in (("plan", "evidence-plan"), ("collect", "evidence-collect")):
        p_e = sub_ev.add_parser(sub_name, help=f"Run {op}.")
        p_e.add_argument("name", help="VM name.")
        p_e.add_argument("--guest-roots", nargs="+", required=True)
        p_e.add_argument("--evidence-root", required=True)
        if op == "evidence-collect":
            p_e.add_argument("-op", "--operation-id")
            p_e.add_argument("--prompt-credential", action="store_true")
        p_e.set_defaults(_builder=_build_evidence(op))
        _add_common_flags(p_e, allow_apply=(op == "evidence-collect"))

    # checkpoint group
    p_cp = sub.add_parser("checkpoint", help="Standard checkpoint management.")
    sub_cp = p_cp.add_subparsers(dest="checkpoint_cmd", metavar="<action>", required=True)
    p_cpl = sub_cp.add_parser("list", help="List checkpoints for a VM.")
    p_cpl.add_argument("name", help="VM name.")
    p_cpl.set_defaults(_builder=_build_checkpoint("checkpoints"))
    _add_common_flags(p_cpl)

    p_cpc = sub_cp.add_parser("create", help="Create a named checkpoint.")
    p_cpc.add_argument("name", help="VM name.")
    p_cpc.add_argument("checkpoint_name", help="Checkpoint name.")
    p_cpc.set_defaults(_builder=_build_checkpoint("checkpoint"))
    _add_common_flags(p_cpc, allow_apply=True)

    p_cpb = sub_cp.add_parser("baseline", help="Create a baseline checkpoint.")
    p_cpb.add_argument("name", help="VM name.")
    p_cpb.set_defaults(_builder=_build_checkpoint("baseline"))
    _add_common_flags(p_cpb, allow_apply=True)

    p_cpt = sub_cp.add_parser("transaction", help="Run transactional Off -> Standard checkpoint -> optional Restart.")
    p_cpt.add_argument("name", help="VM name.")
    p_cpt.add_argument("checkpoint_name", help="Checkpoint name.")
    p_cpt.add_argument("--restart-after", action="store_true")
    p_cpt.add_argument("--authorize-vm-lifecycle", action="store_true")
    p_cpt.add_argument("--prompt-credential", action="store_true")
    p_cpt.set_defaults(_builder=_build_checkpoint("lifecycle-transaction"))
    _add_common_flags(p_cpt, allow_apply=True)

    # workflow group
    p_wf = sub.add_parser("workflow", help="Durable workflow planning, execution, resume, and diagnostics.")
    sub_wf = p_wf.add_subparsers(dest="workflow_cmd", metavar="<action>", required=True)

    p_wfp = sub_wf.add_parser("plan", help="Validate and plan a workflow JSON file.")
    p_wfp.add_argument("file", help="Workflow JSON path.")
    p_wfp.set_defaults(_builder=_build_workflow("workflow-plan"))
    _add_common_flags(p_wfp, allow_manifest_root=False)

    p_wfr = sub_wf.add_parser("run", help="Execute a workflow JSON file.")
    p_wfr.add_argument("file", help="Workflow JSON path.")
    p_wfr.add_argument("-op", "--operation-id")
    p_wfr.add_argument("-or", "--operation-root")
    p_wfr.add_argument("--authorize-host-mutation", action="store_true")
    p_wfr.add_argument("--authorize-vm-lifecycle", action="store_true")
    p_wfr.add_argument("--authorize-guest-mutation", action="store_true")
    p_wfr.add_argument("--authorize-guest-exec", action="store_true")
    p_wfr.add_argument("--authorize-elevation", action="store_true")
    p_wfr.add_argument("--prompt-credential", action="store_true")
    p_wfr.set_defaults(_builder=_build_workflow("workflow-apply"))
    _add_common_flags(p_wfr, allow_apply=True)

    p_wfs = sub_wf.add_parser("status", help="Inspect workflow operation journal status.")
    p_wfs.add_argument("operation_id", help="Operation ID.")
    p_wfs.add_argument("-or", "--operation-root")
    p_wfs.set_defaults(_builder=_build_workflow("workflow-status"))
    _add_common_flags(p_wfs, allow_manifest_root=False)

    p_wfres = sub_wf.add_parser("resume", help="Resume an interrupted or paused workflow.")
    p_wfres.add_argument("operation_id", help="Operation ID.")
    p_wfres.add_argument("-or", "--operation-root")
    p_wfres.add_argument("--authorize-host-mutation", action="store_true")
    p_wfres.add_argument("--authorize-vm-lifecycle", action="store_true")
    p_wfres.add_argument("--authorize-guest-mutation", action="store_true")
    p_wfres.add_argument("--authorize-guest-exec", action="store_true")
    p_wfres.add_argument("--authorize-elevation", action="store_true")
    p_wfres.add_argument("--prompt-credential", action="store_true")
    p_wfres.set_defaults(_builder=_build_workflow("workflow-resume"))
    _add_common_flags(p_wfres, allow_apply=True)

    p_wfd = sub_wf.add_parser("doctor", help="Diagnose stale locks or corrupt workflow journals.")
    p_wfd.add_argument("operation_id", help="Operation ID.")
    p_wfd.add_argument("-or", "--operation-root")
    p_wfd.set_defaults(_builder=_build_workflow("workflow-doctor"))
    _add_common_flags(p_wfd, allow_manifest_root=False)

    p_wfv = sub_wf.add_parser("validate", help="Validate workflow JSON schema and DAG.")
    p_wfv.add_argument("file", help="Workflow JSON path.")
    p_wfv.set_defaults(_builder=_build_workflow("workflow-plan"))
    _add_common_flags(p_wfv, allow_manifest_root=False)

    p_wfrs = sub_wf.add_parser("results", help="Summarize workflow operation receipts and evidence.")
    p_wfrs.add_argument("operation_id", help="Operation ID.")
    p_wfrs.add_argument("-or", "--operation-root")
    p_wfrs.set_defaults(_builder=_build_workflow("workflow-results"))
    _add_common_flags(p_wfrs, allow_manifest_root=False)

    # Phase 3-6 additions: restart, host, media, boot prepare/troubleshoot, setup plan/status/guide,
    # guest wait/identity/inventory/run-script/reboot, evidence inspect, checkpoint inspect, approval
    p_rst = sub.add_parser("restart", help="Gracefully restart an owned VM and wait for guest readiness.")
    p_rst.add_argument("name", help="VM name or ID.")
    p_rst.add_argument("--authorize-vm-lifecycle", action="store_true")
    p_rst.add_argument("--prompt-credential", action="store_true")
    p_rst.set_defaults(_builder=_build_checkpoint("guest-reboot"))
    _add_common_flags(p_rst, allow_apply=True)

    p_host = sub.add_parser("host", help="Host Hyper-V diagnostics and resource checks.")
    sub_host = p_host.add_subparsers(dest="host_cmd", metavar="<action>", required=True)
    p_hd = sub_host.add_parser("doctor", help="Check host Hyper-V and stale lock health.")
    p_hd.set_defaults(_builder=_build_simple("doctor", positional_name=False))
    _add_common_flags(p_hd, allow_manifest_root=False)
    p_hr = sub_host.add_parser("resources", help="Inspect host CPU, RAM, and disk availability.")
    p_hr.add_argument("-rb", "--min-reserve-bytes", type=int)
    p_hr.set_defaults(_builder=_build_simple("host-resources", positional_name=False))
    _add_common_flags(p_hr, allow_manifest_root=False)

    p_media = sub.add_parser("media", help="ISO verification and VM DVD media management.")
    sub_media = p_media.add_subparsers(dest="media_cmd", metavar="<type>", required=True)
    p_iso = sub_media.add_parser("iso", help="ISO operations.")
    sub_iso = p_iso.add_subparsers(dest="iso_cmd", metavar="<action>", required=True)
    p_iv = sub_iso.add_parser("verify", help="Verify ISO readability, size, and optional SHA-256.")
    p_iv.add_argument("iso", help="ISO path.")
    p_iv.add_argument("--expected-sha256")
    p_iv.set_defaults(_builder=lambda ns: (["-o", "iso-verify", "-IsoPath", ns.iso] + (["-ExpectedSha256", ns.expected_sha256] if ns.expected_sha256 else []) + (["-Json"] if ns.json else []), False))
    _add_common_flags(p_iv, allow_manifest_root=False)
    p_ia = sub_iso.add_parser("attach", help="Attach ISO to VM DVD drive.")
    p_ia.add_argument("name", help="VM name or ID.")
    p_ia.add_argument("iso", help="ISO path.")
    p_ia.set_defaults(_builder=_build_simple("iso-attach"))
    _add_common_flags(p_ia, allow_apply=True)
    p_id = sub_iso.add_parser("detach", help="Detach ISO from VM DVD drive.")
    p_id.add_argument("name", help="VM name or ID.")
    p_id.set_defaults(_builder=_build_simple("iso-detach"))
    _add_common_flags(p_id, allow_apply=True)

    p_bp = sub_boot.add_parser("prepare", help="Configure UEFI firmware boot order.")
    p_bp.add_argument("name", help="VM name or ID.")
    p_bp.add_argument("--prefer-dvd", action="store_true")
    p_bp.set_defaults(_builder=lambda ns: (["-o", "boot-prepare", "-Name", ns.name] + (["-PreferDvd"] if ns.prefer_dvd else []) + (["-ManifestRoot", ns.manifest_root] if ns.manifest_root else []) + (["-Apply"] if ns.apply else []) + (["-Json"] if ns.json else []), False))
    _add_common_flags(p_bp, allow_apply=True)
    p_bt = sub_boot.add_parser("troubleshoot", help="Diagnose boot order and DVD prompt recovery.")
    p_bt.add_argument("name", help="VM name or ID.")
    p_bt.set_defaults(_builder=_build_simple("boot-troubleshoot"))
    _add_common_flags(p_bt)

    for sname in ("plan", "status", "guide"):
        p_sg = sub_setup.add_parser(sname, help=f"Windows Setup {sname} report.")
        p_sg.add_argument("name", help="VM name or ID.")
        p_sg.set_defaults(_builder=_build_simple("setup-report"))
        _add_common_flags(p_sg)

    p_gw = sub_guest.add_parser("wait", help="Wait for PowerShell Direct guest readiness.")
    p_gw.add_argument("name", help="VM name or ID.")
    p_gw.add_argument("--timeout-seconds", type=int, default=120)
    p_gw.add_argument("--prompt-credential", action="store_true")
    p_gw.set_defaults(_builder=lambda ns: (["-o", "guest-wait", "-Name", ns.name, "-TimeoutSeconds", str(ns.timeout_seconds)] + (["-PromptCredential"] if ns.prompt_credential else []) + (["-ManifestRoot", ns.manifest_root] if ns.manifest_root else []) + (["-Json"] if ns.json else []), bool(ns.prompt_credential)))
    _add_common_flags(p_gw)

    p_gi = sub_guest.add_parser("identity", help="Verify guest OS, hostname, and local admin token.")
    p_gi.add_argument("name", help="VM name or ID.")
    p_gi.add_argument("--prompt-credential", action="store_true")
    p_gi.set_defaults(_builder=lambda ns: (["-o", "guest-identity", "-Name", ns.name] + (["-PromptCredential"] if ns.prompt_credential else []) + (["-ManifestRoot", ns.manifest_root] if ns.manifest_root else []) + (["-Json"] if ns.json else []), bool(ns.prompt_credential)))
    _add_common_flags(p_gi)

    p_ginv = sub_guest.add_parser("inventory", help="Inspect guest processes, services, and scheduled tasks.")
    p_ginv.add_argument("name", help="VM name or ID.")
    p_ginv.add_argument("--processes", action="store_true")
    p_ginv.add_argument("--services", action="store_true")
    p_ginv.add_argument("--tasks", action="store_true")
    p_ginv.add_argument("--prompt-credential", action="store_true")
    p_ginv.set_defaults(_builder=lambda ns: (["-o", "guest-inventory", "-Name", ns.name] + (["-IncludeProcesses"] if ns.processes else []) + (["-IncludeServices"] if ns.services else []) + (["-IncludeTasks"] if ns.tasks else []) + (["-PromptCredential"] if ns.prompt_credential else []) + (["-ManifestRoot", ns.manifest_root] if ns.manifest_root else []) + (["-Json"] if ns.json else []), bool(ns.prompt_credential)))
    _add_common_flags(p_ginv)

    p_grs = sub_guest.add_parser("run-script", help="Execute a SHA-256-verified PowerShell script inside the guest.")
    p_grs.add_argument("name", help="VM name or ID.")
    p_grs.add_argument("--script", required=True, help="Local .ps1 script path.")
    p_grs.add_argument("--expected-sha256")
    p_grs.add_argument("-w", "--working-directory", default=r"C:\Windows\Temp")
    p_grs.add_argument("-op", "--operation-id")
    p_grs.add_argument("--authorize-guest-exec", action="store_true")
    p_grs.add_argument("--prompt-credential", action="store_true")
    p_grs.add_argument("exec_args", nargs="*", help="Script arguments (or pass after --).")
    p_grs.set_defaults(_builder=lambda ns: (["-o", "guest-run-script", "-Name", ns.name, "-ScriptPath", ns.script, "-WorkingDirectory", ns.working_directory] + (["-ArgumentList", *ns.exec_args] if ns.exec_args else []) + (["-ExpectedSha256", ns.expected_sha256] if ns.expected_sha256 else []) + (["-OperationId", ns.operation_id] if ns.operation_id else []) + (["-AuthorizeGuestExec"] if ns.authorize_guest_exec else []) + (["-PromptCredential"] if ns.prompt_credential else []) + (["-ManifestRoot", ns.manifest_root] if ns.manifest_root else []) + (["-Apply"] if ns.apply else []) + (["-Json"] if ns.json else []), bool(ns.prompt_credential)))
    _add_common_flags(p_grs, allow_apply=True)

    p_grb = sub_guest.add_parser("reboot", help="Gracefully reboot an owned VM and wait for readiness.")
    p_grb.add_argument("name", help="VM name or ID.")
    p_grb.add_argument("--authorize-vm-lifecycle", action="store_true")
    p_grb.add_argument("--prompt-credential", action="store_true")
    p_grb.set_defaults(_builder=_build_checkpoint("guest-reboot"))
    _add_common_flags(p_grb, allow_apply=True)

    p_evi = sub_ev.add_parser("inspect", help="Inspect collected evidence for an operation ID.")
    p_evi.add_argument("operation_id", help="Operation ID.")
    p_evi.add_argument("-or", "--operation-root")
    p_evi.set_defaults(_builder=_build_workflow("evidence-inspect"))
    _add_common_flags(p_evi, allow_manifest_root=False)

    p_cpi = sub_cp.add_parser("inspect", help="Inspect a checkpoint by name or ID.")
    p_cpi.add_argument("name", help="VM name or ID.")
    p_cpi.add_argument("--checkpoint-name")
    p_cpi.add_argument("--checkpoint-id")
    p_cpi.set_defaults(_builder=lambda ns: (["-o", "checkpoint-inspect", "-Name", ns.name] + (["-CheckpointName", ns.checkpoint_name] if ns.checkpoint_name else []) + (["-CheckpointId", ns.checkpoint_id] if ns.checkpoint_id else []) + (["-ManifestRoot", ns.manifest_root] if ns.manifest_root else []) + (["-Json"] if ns.json else []), False))
    _add_common_flags(p_cpi)

    p_app = sub.add_parser("approval", help="Bounded approved-plan request and execution.")
    sub_app = p_app.add_subparsers(dest="approval_cmd", metavar="<action>", required=True)
    p_apr = sub_app.add_parser("request", help="Create a SHA-256-sealed approved-plan request.")
    p_apr.add_argument("file", help="Workflow JSON path.")
    p_apr.add_argument("--output", required=True, help="Output request JSON path.")
    p_apr.add_argument("--capabilities", nargs="+")
    p_apr.add_argument("-op", "--operation-id")
    p_apr.add_argument("--expected-vm-id")
    p_apr.set_defaults(_builder=lambda ns: (["-o", "approval-request", "-WorkflowPath", ns.file, "-OutputPath", ns.output] + (["-AllowedCapabilities", *ns.capabilities] if ns.capabilities else []) + (["-OperationId", ns.operation_id] if ns.operation_id else []) + (["-ExpectedVmId", ns.expected_vm_id] if ns.expected_vm_id else []) + (["-Json"] if ns.json else []), False))
    _add_common_flags(p_apr, allow_manifest_root=False)

    p_api = sub_app.add_parser("inspect", help="Validate an approved-plan request.")
    p_api.add_argument("request", help="Request JSON path.")
    p_api.add_argument("--expected-digest")
    p_api.set_defaults(_builder=lambda ns: (["-o", "approval-inspect", "-RequestPath", ns.request] + (["-ExpectedRequestDigest", ns.expected_digest] if ns.expected_digest else []) + (["-Json"] if ns.json else []), False))
    _add_common_flags(p_api, allow_manifest_root=False)

    p_ape = sub_app.add_parser("execute", help="Execute an approved-plan request via Invoke-VmLabApprovedPlan.ps1.")
    p_ape.add_argument("request", help="Request JSON path.")
    p_ape.add_argument("--expected-digest")
    p_ape.add_argument("--operator-consent", action="store_true")
    p_ape.add_argument("--dry-run", action="store_true")
    p_ape.set_defaults(
        _script_name="Invoke-VmLabApprovedPlan.ps1",
        _builder=lambda ns: (["-RequestPath", ns.request] + (["-ExpectedRequestDigest", ns.expected_digest] if ns.expected_digest else []) + (["-OperatorConsent"] if ns.operator_consent else []) + (["-DryRun"] if ns.dry_run else []), False),
    )
