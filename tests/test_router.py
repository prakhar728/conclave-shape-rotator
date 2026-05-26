import pytest
from skills.router import SkillRouter


def test_register_and_invoke():
    router = SkillRouter()
    router.register("echo", lambda text: text)
    assert router.invoke("echo", text="hello") == "hello"


def test_list_skills():
    router = SkillRouter()
    router.register("a", lambda: None)
    router.register("b", lambda: None)
    assert sorted(router.list_skills()) == ["a", "b"]


def test_invoke_unregistered_raises():
    router = SkillRouter()
    with pytest.raises(KeyError, match="not registered"):
        router.invoke("nonexistent")
