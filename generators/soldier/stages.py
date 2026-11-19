"""Stage dispatch for soldier_unit.py (the stages that are not per-body villager stages)."""


def run(stage, cfg, work, A, rel):
    if stage == "props":
        from . import props
        props.run(cfg, work, only=A["only"].split(",") if "only" in A else None, rel=rel)
    elif stage == "assemble":
        from . import assemble
        assemble.run(cfg, work, A, rel)
    elif stage == "clips":
        from . import clips
        clips.run(cfg, work, A, rel)
    elif stage == "finalize":
        from . import finalize
        finalize.run(cfg, work, A, rel)
    else:
        raise SystemExit("unknown --stage " + repr(stage))
