import asyncio
import pytest
from unittest.mock import Mock


@pytest.fixture
def bot():
    from jenkins_epo.bot import Bot

    bot = Bot().workon(Mock())
    bot.current.SETTINGS.COLLABORATORS = ['trusted']

    return bot


@pytest.fixture
def instruction():
    from jenkins_epo.bot import Instruction

    return Instruction(author='jenkins', name='security-feedback-processed')


def test_defaults(bot):
    assert bot.current.secure is False
    assert bot.current.security_feedback_processed is False


@pytest.mark.asyncio
@asyncio.coroutine
def test_non_pr(bot):
    bot.current.head.author = None  # cancel out mock
    bot.extensions_map['security'].begin()
    assert bot.current.secure is False
    yield from bot.extensions_map['security'].run()


@pytest.mark.asyncio
@asyncio.coroutine
def test_untrusted_author(bot, instruction):
    from jenkins_epo.extensions.core import SkipHead

    bot.current.head.author = 'untrusted'
    bot.extensions_map['security'].begin()
    assert bot.current.secure is False
    with pytest.raises(SkipHead):
        yield from bot.extensions_map['security'].run()
    assert bot.current.head.comment.call_args_list
    assert 'security-feedback-processed' in str(
        bot.current.head.comment.call_args_list[0]
    )

    bot.current.head.comment = Mock()  # reset calls
    bot.extensions_map['security'].process_instruction(instruction)
    with pytest.raises(SkipHead):
        yield from bot.extensions_map['security'].run()
    assert not bot.current.head.comment.call_args_list


@pytest.mark.asyncio
@asyncio.coroutine
def test_trusted_author(bot):
    bot.current.head.author = 'trusted'
    bot.extensions_map['security'].begin()
    assert bot.current.secure is True
    yield from bot.extensions_map['security'].run()
