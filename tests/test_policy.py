import json

import httpx2
import pytest
from typesafe_sdk import TypeSafeClient

from mario_jev.policy import JevPolicy


@pytest.mark.parametrize(
    "grounded, held, sustain, movement, expected, ceiling, ceiling_hop",
    [
        (True, False, 0.1, "run_right", "right_run_jump", False, 0.1),
        (True, True, 0.9, "run_right", "right_run", False, 0.1),
        (False, True, 0.9, "run_right", "right_run_jump", False, 0.1),
        (False, True, 0.1, "run_right", "right_run", False, 0.1),
        (True, False, 0.1, "brake_left", "left_jump", False, 0.1),
        (True, False, 0.1, "wait", "jump", False, 0.1),
        (True, False, 0.1, "run_right", "right_run", True, 0.1),
        (True, False, 0.1, "run_right", "right_run_jump", True, 0.9),
    ],
)
def test_real_sdk_request_and_response(
    monkeypatch, grounded, held, sustain, movement, expected, ceiling, ceiling_hop
):
    def handle(request):
        body = json.loads(request.content)
        assert body["model"] == "jev-latest"
        assert body["questions"]["movement"]["type"] == "choice"
        assert body["state"]["action_frames"] == 6
        return httpx2.Response(
            200,
            json={
                "model": "jev-latest",
                "usage": {"input_tokens": 100, "output_tokens": 10},
                "answers": {
                    "movement": {
                        "type": "choice",
                        "choice": movement,
                        "confidence": 0.8,
                        "probabilities": {"run_right": 0.9, "walk_right": 0.1},
                    },
                    "start_jump": {"type": "noul", "noul": 0.9},
                    "ceiling_hop": {"type": "noul", "noul": ceiling_hop},
                    "sustain_jump": {"type": "noul", "noul": sustain},
                },
            },
        )

    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    policy = JevPolicy()
    policy.client.close()
    policy.client = TypeSafeClient(
        api_key="test-key", transport=httpx2.MockTransport(handle)
    )
    try:
        action, diagnostics = policy.choose(
            {
                "action_frames": 6,
                "mario": {"grounded": grounded},
                "jump_already_held": held,
                "jump_corridor": {"low_ceiling_before_nearest_threat": ceiling},
            }
        )
        assert action == expected
        assert diagnostics["usage"]["input_tokens"] == 100
        assert diagnostics["probabilities"]["run_right"] == 0.9
    finally:
        policy.close()


def test_world12_opening_profile_starts_and_sustains_jump(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    policy = JevPolicy(env_id="SuperMarioBros-1-2-v0")
    try:
        base = {
            "jump_corridor": {
                "low_ceiling_now": False,
                "low_ceiling_before_nearest_threat": False,
            },
            "nearby_objects": [
                {"kind": "goomba", "dx": 35, "defeated": False},
                {"kind": "goomba", "dx": 51, "defeated": False},
            ],
            "jump_already_held": False,
        }
        action, reason = policy._world12_opening_override(
            {**base, "mario": {"x": 140, "grounded": True}}, "left"
        )
        assert action == "right_run_jump"
        assert reason == "world12_pair_short_hop"

        airborne = {**base, "mario": {"x": 180, "grounded": False}}
        action, reason = policy._world12_opening_override(airborne, "right_run")
        assert action == "right_run_jump"
        assert reason == "world12_pair_sustain_jump"
    finally:
        policy.close()


def test_world12_koopa_profile_rejects_braking_into_threat(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    policy = JevPolicy(env_id="SuperMarioBros-1-2-v0")
    try:
        state = {
            "mario": {"x": 865, "grounded": True},
            "jump_already_held": False,
            "jump_corridor": {
                "low_ceiling_now": True,
                "low_ceiling_before_nearest_threat": True,
            },
            "nearby_objects": [
                {
                    "kind": "green_koopa",
                    "dx": 56,
                    "same_height": True,
                    "defeated": False,
                }
            ],
        }
        action, reason = policy._world12_opening_override(state, "left")
        assert action == "right_run"
        assert reason == "world12_koopa_approach"

        state["mario"] = {"x": 877, "grounded": True}
        state["nearby_objects"][0]["dx"] = 41
        action, reason = policy._world12_opening_override(state, "left")
        assert action == "right_run_jump"
        assert reason == "world12_koopa_short_hop"
    finally:
        policy.close()
