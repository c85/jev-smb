"""Run bounded, logged episodes; emulator pauses during model calls."""

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from dotenv import load_dotenv

from .history import ObservationMemory
from .policy import ACTIONS, JevPolicy, ScriptedPolicy
from .runner import execute_action


def positive(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def parse_route(value):
    route = []
    for level in value.split(","):
        parts = level.strip().split("-")
        if len(parts) != 2:
            raise argparse.ArgumentTypeError(
                "route levels must look like 1-1,1-2"
            )
        try:
            world, stage = (int(part) for part in parts)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                "route levels must look like 1-1,1-2"
            ) from exc
        if world not in range(1, 9) or stage not in range(1, 5):
            raise argparse.ArgumentTypeError(
                "route levels must use worlds 1-8 and stages 1-4"
            )
        route.append((world, stage))
    if not route:
        raise argparse.ArgumentTypeError("route cannot be empty")
    return route


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", choices=["jev", "scripted"], default="jev")
    parser.add_argument("--model", default="jev-latest")
    parser.add_argument(
        "--world", type=int, choices=range(1, 9), default=1, help="World (default: 1)"
    )
    parser.add_argument(
        "--stage",
        type=int,
        choices=range(1, 5),
        default=1,
        help="Stage within the world (default: 1)",
    )
    parser.add_argument(
        "--route",
        type=parse_route,
        help="Comma-separated levels to run continuously, e.g. 1-1,1-2",
    )
    parser.add_argument("--frames", type=positive, default=4)
    parser.add_argument(
        "--decisions",
        type=positive,
        default=500,
        help="Maximum decisions per episode (and API calls with Jev)",
    )
    parser.add_argument("--episodes", type=positive, default=1)
    parser.add_argument(
        "--history",
        type=positive,
        default=12,
        help="Recent transitions to send to Jev (default: 12)",
    )
    parser.add_argument("--headless", action="store_true")
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Open a live local dashboard alongside the game window",
    )
    parser.add_argument(
        "--dashboard-port",
        type=int,
        default=8765,
        help="Local dashboard port (default: 8765)",
    )
    parser.add_argument("--seed", type=int, default=123)
    parser.add_argument("--log-dir", type=Path, default=Path("runs"))
    parser.add_argument(
        "--dump-state",
        action="store_true",
        help="Print initial RAM-derived state without model calls",
    )
    parser.add_argument(
        "--replay", type=Path, help="Replay a gameplay log without API calls"
    )
    parser.add_argument(
        "--speed", type=positive, default=1, help="Replay speed multiplier (default: 1)"
    )
    args = parser.parse_args()
    route = args.route or [(args.world, args.stage)]
    route_env_ids = [f"SuperMarioBros-{world}-{stage}-v0" for world, stage in route]
    env_id = route_env_ids[0]
    if args.replay:
        if args.route:
            parser.error("--route cannot be combined with --replay")
        from .replay import replay

        try:
            replay(
                args.replay,
                args.headless,
                args.speed,
                dashboard=args.dashboard,
                dashboard_port=args.dashboard_port,
            )
        except KeyboardInterrupt:
            print("Replay stopped.")
        except Exception as exc:  # noqa: BLE001 -- CLI error boundary
            parser.exit(1, f"Replay failed ({type(exc).__name__}): {exc}\n")
        return
    load_dotenv()
    if (
        args.policy == "jev"
        and not args.dump_state
        and not os.getenv("TYPESAFE_API_KEY", "").strip()
    ):
        parser.error(
            "Set TYPESAFE_API_KEY in .env or your environment, or use --policy scripted"
        )

    import gym_super_mario_bros
    from nes_py.wrappers import JoypadSpace

    env = None
    policy = None
    dashboard = None
    frame_callback = None
    dashboard_history = []
    dashboard_x_history = []

    def make_env(stage_env_id):
        return JoypadSpace(
            gym_super_mario_bros.make(
                stage_env_id,
                render_mode="rgb_array" if args.headless else "human",
            ),
            list(ACTIONS.values()),
        )

    try:
        if args.dump_state:
            env = make_env(route_env_ids[0])
            _, info = env.reset(seed=args.seed)
            print(
                json.dumps(
                    ObservationMemory(args.history).observe(
                        env.unwrapped.ram, info, args.frames
                    ),
                    indent=2,
                )
            )
            return
        policy = (
            JevPolicy(args.model, env_id=env_id)
            if args.policy == "jev"
            else ScriptedPolicy()
        )
        args.log_dir.mkdir(parents=True, exist_ok=True)
        path = args.log_dir / (
            datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + ".jsonl"
        )
        print(f"Logging to {path.resolve()}")
        if args.dashboard:
            from .dashboard import DashboardServer

            dashboard = DashboardServer(args.dashboard_port).start()
            frame_callback = dashboard.publish_frame
            dashboard.publish(
                {
                    "status": "running",
                    "kind": "run",
                    "env": env_id,
                    "route": route_env_ids,
                    "policy": args.policy,
                    "model": args.model,
                    "episodes": args.episodes,
                    "decisions_total": args.decisions * len(route_env_ids),
                    "message": "Controller is warming up",
                }
            )
        with path.open("w") as log:

            def write(record):
                log.write(json.dumps(record) + "\n")
                log.flush()

            write(
                {
                    "type": "config",
                    "policy": args.policy,
                    "model": args.model,
                    "frames": args.frames,
                    "decisions": args.decisions,
                    "episodes": args.episodes,
                    "history": args.history,
                    "interrupt_on_landing": True,
                    "seed": args.seed,
                    "env": env_id,
                    "route": route_env_ids,
                }
            )
            for episode in range(args.episodes):
                for stage_index, stage_env_id in enumerate(route_env_ids):
                    if env is not None:
                        env.close()
                    env = make_env(stage_env_id)
                    set_env_id = getattr(policy, "set_env_id", None)
                    if set_env_id is not None:
                        set_env_id(stage_env_id)
                    dashboard_history = []
                    dashboard_x_history = []
                    if dashboard is not None:
                        dashboard.publish(
                            {
                                "status": "running",
                                "kind": "run",
                                "env": stage_env_id,
                                "route": route_env_ids,
                                "episode": episode,
                                "stage_index": stage_index,
                                "episodes": args.episodes,
                                "message": f"Starting {stage_env_id}",
                            }
                        )
                    _, info = env.reset(seed=args.seed + episode)
                    if not args.headless:
                        env.render()
                        # nes-py exposes its pyglet window through the viewer.
                        env.unwrapped.viewer._window.set_size(800, 600)
                        env.render()
                    memory = ObservationMemory(args.history)
                    max_x = int(info["x_pos"])
                    total_reward = 0.0
                    completed = False
                    terminated = truncated = False
                    for decision in range(args.decisions):
                        state = memory.observe(env.unwrapped.ram, info, args.frames)
                        started = perf_counter()
                        action, diagnostics = policy.choose(state)
                        latency = (perf_counter() - started) * 1000
                        info, reward, terminated, truncated, samples = execute_action(
                            env,
                            action,
                            args.frames,
                            args.headless,
                            frame_callback=frame_callback,
                        )
                        executed = len(samples)
                        max_x = max(max_x, *(sample["x"] for sample in samples))
                        completed |= bool(info.get("flag_get"))
                        transition = memory.finish(
                            state,
                            env.unwrapped.ram,
                            info,
                            action,
                            executed,
                            reward,
                            terminated or truncated,
                            samples=samples,
                        )
                        total_reward += reward
                        write(
                            {
                                "type": "decision",
                                "episode": episode,
                                "stage_index": stage_index,
                                "env": stage_env_id,
                                "decision": decision,
                                "state": state,
                                "action": action,
                                "latency_ms": round(latency, 2),
                                "frames_executed": executed,
                                "transition": transition,
                                "reward": reward,
                                "result": {
                                    "x": int(info["x_pos"]),
                                    "y": int(env.unwrapped.ram[0xCE]),
                                    "flag_get": completed,
                                    "terminated": bool(terminated),
                                    "truncated": bool(truncated),
                                },
                                **diagnostics,
                            }
                        )
                        if dashboard is not None:
                            detail = diagnostics.get("decisions", {})
                            dashboard_history = [
                                *dashboard_history,
                                {
                                    "decision": decision,
                                    "action": action,
                                    "x": int(info["x_pos"]),
                                    "events": transition.get("events", []),
                                },
                            ][-32:]
                            dashboard_x_history = [
                                *dashboard_x_history,
                                {"decision": decision, "x": int(info["x_pos"])},
                            ][-160:]
                            dashboard.publish(
                                {
                                    "status": "complete" if completed else "running",
                                    "episode": episode,
                                    "stage_index": stage_index,
                                    "env": stage_env_id,
                                    "route": route_env_ids,
                                    "episodes": args.episodes,
                                    "decision": decision,
                                    "decisions_total": args.decisions,
                                    "x": int(info["x_pos"]),
                                    "y": int(env.unwrapped.ram[0xCE]),
                                    "max_x": max_x,
                                    "reward": total_reward,
                                    "time_remaining": info.get("time"),
                                    "flag_get": completed,
                                    "action": action,
                                    "frames_executed": executed,
                                    "latency_ms": latency,
                                    "decision_detail": detail,
                                    "events": transition.get("events", []),
                                    "motion": state["mario"].get("motion", "position"),
                                    "message": "Flag reached" if completed else "Jev is steering Mario",
                                    "history": dashboard_history,
                                    "x_history": dashboard_x_history,
                                }
                            )
                        if decision % 25 == 0:
                            print(
                                f"Episode {episode + 1}, {stage_env_id}, decision {decision}: x={info['x_pos']} action={action} latency={latency:.0f}ms"
                            )
                        if terminated or truncated:
                            break
                    summary = {
                        "type": "summary",
                        "episode": episode,
                        "stage_index": stage_index,
                        "env": stage_env_id,
                        "decisions": decision + 1,
                        "max_x": max_x,
                        "completed": completed,
                        "route_complete": completed and stage_index == len(route_env_ids) - 1,
                        "reward": total_reward,
                        "stop_reason": "completed"
                        if completed
                        else "terminated"
                        if terminated
                        else "truncated"
                        if truncated
                        else "decision_limit",
                    }
                    write(summary)
                    print(json.dumps(summary))
                    next_stage = completed and stage_index + 1 < len(route_env_ids)
                    if dashboard is not None:
                        dashboard.publish(
                            {
                                "status": "running" if next_stage else "complete" if completed else "stopped",
                                "episode": episode,
                                "stage_index": stage_index,
                                "env": stage_env_id,
                                "route": route_env_ids,
                                "decisions_total": summary["decisions"],
                                "flag_get": completed,
                                "message": f"Starting {route_env_ids[stage_index + 1]}" if next_stage else "Level complete" if completed else f"Run ended: {summary['stop_reason']}",
                            }
                        )
                    if not completed and stage_index + 1 < len(route_env_ids):
                        break
    except KeyboardInterrupt:
        print("Stopped.")
    except Exception as exc:  # noqa: BLE001 -- CLI boundary provides a concise error
        parser.exit(1, f"Mario run failed ({type(exc).__name__}): {exc}\n")
    finally:
        if dashboard is not None:
            dashboard.stop()
        if policy is not None:
            policy.close()
        if env is not None:
            env.close()
