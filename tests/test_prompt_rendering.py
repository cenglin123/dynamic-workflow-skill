"""Prompt template rendering tests — contract assertions P-01~P-09."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import scheduler


@pytest.fixture
def prompt_file(tmp_path):
    """Create a prompt templates JSON file."""
    templates = {
        "pipe": "Process item {{item}} at stage {{stage}} in domain {{domain}}",
        "waitall": "Batch {{batch_idx}}: process {{item}} at {{stage}}",
        "loop": "Round {{round}}: search in domain {{domain}}, seen={{seen}}",
        "loop_finder": "Find new items, round {{round}}, context={{context}}",
    }
    path = tmp_path / "templates.json"
    path.write_text(json.dumps(templates), encoding="utf-8")
    return str(path)


@pytest.fixture
def init_with_prompt(tmp_dir, prompt_file):
    """Initialize a workflow with prompt templates."""
    def _init(slug="test", mode="pipe", items="a,b", stages="x,y", budget=None):
        args = type("Args", (), {
            "slug": slug,
            "mode": mode,
            "items": items,
            "stages": stages,
            "budget": budget,
            "concurrency": 16,
            "dry_threshold": 2,
            "max_rounds": 20,
            "max_retries": 3,
            "framework": None,
            "prompt_file": prompt_file,
            "dir": tmp_dir,
        })()
        scheduler.cmd_init(args)
        return slug
    return _init


class TestP01_PromptTemplatesLoaded:
    """P-01: --prompt-file loads templates into state.prompt_templates."""

    def test_templates_in_state(self, init_with_prompt, read_state):
        init_with_prompt(slug="t", mode="pipe")
        state = read_state("t")
        assert "prompt_templates" in state
        assert "pipe" in state["prompt_templates"]
        assert "loop" in state["prompt_templates"]

    def test_no_prompt_file(self, init_pipe, read_state):
        init_pipe(slug="t", items="a", stages="x")
        state = read_state("t")
        assert state["prompt_templates"] == {}


class TestP02_ItemReplacement:
    """P-02: _render_prompt replaces {{item}} with current item name."""

    def test_item_replaced_in_pipe(self, init_with_prompt, do_dispatch):
        init_with_prompt(slug="t", mode="pipe", items="alpha,beta", stages="x,y")
        action = do_dispatch("t")
        assert action["prompt"] is not None
        assert "alpha" in action["prompt"]
        assert "{{item}}" not in action["prompt"]


class TestP03_StageReplacement:
    """P-03: _render_prompt replaces {{stage}} with current stage name."""

    def test_stage_replaced_in_pipe(self, init_with_prompt, do_dispatch):
        init_with_prompt(slug="t", mode="pipe", items="a", stages="research,review")
        action = do_dispatch("t")
        assert action["prompt"] is not None
        assert "research" in action["prompt"]
        assert "{{stage}}" not in action["prompt"]


class TestP04_RoundReplacement:
    """P-04: _render_prompt replaces {{round}} with current loop round."""

    def test_round_replaced_in_loop(self, init_with_prompt, do_dispatch):
        init_with_prompt(slug="t", mode="loop", items="a", stages="x")
        action = do_dispatch("t")
        assert action["prompt"] is not None
        # round should be 1 after first dispatch
        assert "1" in action["prompt"]
        assert "{{round}}" not in action["prompt"]


class TestP05_DomainReplacement:
    """P-05: _render_prompt replaces {{domain}} with config.context.domain."""

    def test_domain_replaced(self, init_with_prompt, do_dispatch, read_state, tmp_dir):
        init_with_prompt(slug="t", mode="pipe", items="a", stages="x")
        # Set domain in context
        state = read_state("t")
        state["config"]["context"]["domain"] = "machine-learning"
        scheduler.save_state(state, tmp_dir)
        template = "Domain: {{domain}}"
        state = {"config": {"context": {"domain": "ml"}}}
        result = scheduler._render_prompt(template, state)
        assert result == "Domain: ml"


class TestP06_SeenReplacement:
    """P-06: _render_prompt replaces {{seen}} with JSON-serialized seen array."""

    def test_seen_replaced(self):
        template = "Seen: {{seen}}"
        state = {"config": {"context": {"seen": ["item1", "item2"]}}}
        result = scheduler._render_prompt(template, state)
        assert "item1" in result
        assert "item2" in result
        assert "{{seen}}" not in result


class TestP07_ContextReplacement:
    """P-07: _render_prompt replaces {{context}} with JSON-serialized full context."""

    def test_context_replaced(self):
        template = "Context: {{context}}"
        state = {"config": {"context": {"domain": "test", "seen": [1, 2]}}}
        result = scheduler._render_prompt(template, state)
        assert "test" in result
        assert "{{context}}" not in result


class TestP08_UnmatchedVariablesPreserved:
    """P-08: unmatched {{variable}} preserved in prompt (no error)."""

    def test_unknown_variable_preserved(self):
        template = "Value: {{unknown_var}} and {{another}}"
        state = {"config": {"context": {}}}
        result = scheduler._render_prompt(template, state)
        assert "{{unknown_var}}" in result
        assert "{{another}}" in result


class TestP09_BatchIdxReplacement:
    """P-09: _render_prompt replaces {{batch_idx}} with current batch index."""

    def test_batch_idx_replaced_in_waitall(self, init_with_prompt, do_dispatch):
        init_with_prompt(slug="t", mode="waitall", items="a", stages="x,y")
        action = do_dispatch("t")
        assert action["prompt"] is not None
        # batch_idx should be 0 for first batch
        assert "0" in action["prompt"]
        assert "{{batch_idx}}" not in action["prompt"]
