"""Deterministic playback of recorded controller actions without API calls."""

import json
import re
from pathlib import Path
from time import sleep

from .policy import ACTIONS


def load_replay(path):
    records = [
        json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()
    ]
    if not records or records[0].get("type") != "config":
        raise ValueError(
            "Replay needs a complete gameplay log beginning with a config record."
        )
    config = records[0]
    route = config.get("route") or [config.get("env")]
    if not route or any(
        not re.fullmatch(r"SuperMarioBros-[1-8]-[1-4]-v0", str(env_id))
        for env_id in route
    ):
        raise ValueError("Replay requires SMB1 world 1-8, stage 1-4 gameplay logs.")
    config["route"] = route
    decisions = [record for record in records if record.get("type") == "decision"]
    if not decisions:
        raise ValueError("No recorded decisions to replay.")
    for record in decisions:
        if record.get("action") not in ACTIONS:
            raise ValueError("Replay contains an unknown action.")
        frames = record.get("frames_executed")
        if type(frames) is not int or frames < 1:
            raise ValueError("Replay frame counts must be positive integers.")
    return config, decisions


def replay(path, headless=False, speed=1.0, dashboard=False, dashboard_port=8765):
    import gym_super_mario_bros
    from nes_py.wrappers import JoypadSpace

    config, decisions = load_replay(path)
    route = config["route"]
    dashboard_server = None
    if dashboard:
        from .dashboard import DashboardServer

        dashboard_server = DashboardServer(dashboard_port).start()
        dashboard_server.publish(
            {
                "status": "running",
                "kind": "replay",
                "env": route[0],
                "route": route,
                "policy": "replay",
                "model": config.get("model", "recorded"),
                "episodes": config.get("episodes", 1),
                "decisions_total": len(decisions),
                "message": "Playing back recorded actions",
            }
        )
    print(f"Replaying {Path(path).resolve()} without API calls")
    env = None
    episode = None
    stage_index = None
    ended = False
    completed = False
    dashboard_history = []
    dashboard_x_history = []
    try:
        for record in decisions:
            record_stage_index = record.get("stage_index", 0)
            if record_stage_index < 0 or record_stage_index >= len(route):
                raise ValueError("Recorded stage is outside the configured route.")
            record_env = record.get("env", route[record_stage_index])
            if record_env != route[record_stage_index]:
                raise ValueError("Recorded stage environment does not match its route.")
            if record["episode"] != episode or record_stage_index != stage_index:
                if env is not None:
                    env.close()
                env = JoypadSpace(
                    gym_super_mario_bros.make(
                        record_env, render_mode="rgb_array" if headless else "human"
                    ),
                    list(ACTIONS.values()),
                )
                episode = record["episode"]
                stage_index = record_stage_index
                env.reset(seed=config["seed"] + episode)
                ended = completed = False
                dashboard_history = []
                dashboard_x_history = []
                if not headless:
                    env.render()
                    env.unwrapped.viewer._window.set_size(800, 600)
            if ended:
                raise ValueError("Recorded action occurs after episode termination.")
            for frame in range(record["frames_executed"]):
                _, _, terminated, truncated, info = env.step(
                    list(ACTIONS).index(record["action"])
                )
                completed |= bool(info.get("flag_get"))
                ended = terminated or truncated
                if not headless:
                    env.render()
                if dashboard_server is not None:
                    dashboard_server.publish_frame(env.unwrapped.screen)
                if not headless or dashboard_server is not None:
                    sleep(1 / (60 * speed))
                if ended and frame + 1 != record["frames_executed"]:
                    raise ValueError(
                        "Replay diverged: episode ended before recorded action finished."
                    )
            expected = record["result"]
            if int(info["x_pos"]) != expected["x"] or (
                "history" in config and int(env.unwrapped.ram[0xCE]) != expected["y"]
            ):
                raise ValueError(
                    f"Replay diverged at episode {episode}, decision {record['decision']}. Use the same emulator dependencies and game version as the original run."
                )
            if dashboard_server is not None:
                dashboard_history = [
                    *dashboard_history,
                    {
                        "decision": record["decision"],
                        "action": record["action"],
                        "x": int(info["x_pos"]),
                        "events": record.get("transition", {}).get("events", []),
                    },
                ][-32:]
                dashboard_x_history = [
                    *dashboard_x_history,
                    {"decision": record["decision"], "x": int(info["x_pos"])},
                ][-160:]
                dashboard_server.publish(
                    {
                        "status": "complete" if completed else "running",
                        "episode": episode,
                        "stage_index": stage_index,
                        "env": record_env,
                        "route": route,
                        "episodes": config.get("episodes", 1),
                        "decision": record["decision"],
                        "decisions_total": len(decisions),
                        "x": int(info["x_pos"]),
                        "y": int(record["result"].get("y", 0)),
                        "max_x": max(item["x"] for item in dashboard_x_history),
                        "reward": sum(
                            float(item.get("reward", 0.0))
                            for item in decisions[: record["decision"] + 1]
                        ),
                        "time_remaining": record.get("state", {}).get("time_remaining"),
                        "flag_get": completed,
                        "action": record["action"],
                        "frames_executed": record["frames_executed"],
                        "latency_ms": record.get("latency_ms", 0.0),
                        "decision_detail": record.get("decisions", {}),
                        "events": record.get("transition", {}).get("events", []),
                        "motion": record.get("state", {}).get("mario", {}).get("motion", "position"),
                        "message": "Flag reached" if completed else "Playing recorded actions",
                        "history": dashboard_history,
                        "x_history": dashboard_x_history,
                    }
                )
            if record["decision"] % 50 == 0 or ended:
                print(
                    f"Episode {episode + 1}, {record_env}, decision {record['decision']}: x={info['x_pos']} completed={completed}"
                )
        print(
            f"Replay verified: {len(decisions)} decisions matched recorded positions. Final episode completed={completed}"
        )
        if dashboard_server is not None:
            dashboard_server.publish(
                {
                    "status": "complete" if completed else "stopped",
                    "flag_get": completed,
                    "message": "Level complete" if completed else "Replay finished",
                    "history": dashboard_history,
                    "x_history": dashboard_x_history,
                }
            )
    finally:
        if env is not None:
            env.close()
        if dashboard_server is not None:
            dashboard_server.stop()
