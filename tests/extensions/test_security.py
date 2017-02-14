import asyncio
import pytest
from unittest.mock import Mock


def test_process_feedback():
    from jenkins_epo.bot import Instruction
    from jenkins_epo.extensions.core import SecurityExtension

    ext = SecurityExtension('sec', Mock())
    ext.current = ext.bot.current
    ext.current.security_feedback_processed = None

    ext.process_instruction(Instruction(
        author='bot', name='security-feedback-processed'
    ))

    assert ext.current.security_feedback_processed


def test_process_allow():
    from jenkins_epo.bot import Instruction
    from jenkins_epo.extensions.core import SecurityExtension

    ext = SecurityExtension('sec', Mock())
    ext.current = ext.bot.current
    ext.current.head.author = 'contributor'
    ext.current.security_feedback_processed = None
    ext.current.SETTINGS.COLLABORATORS = ['owner']
    ext.current.denied_instructions = [
        Instruction(author='contributor', name='skip')
    ]

    ext.process_instruction(Instruction(
        author='owner', name='allow'
    ))

    assert 'contributor' in ext.current.SETTINGS.COLLABORATORS
    assert not ext.current.denied_instructions


@pytest.mark.asyncio
@asyncio.coroutine
def test_non_pr():
    from jenkins_epo.extensions.core import SecurityExtension

    ext = SecurityExtension('sec', Mock())
    ext.current = ext.bot.current
    ext.current.head.author = None

    yield from ext.run()


@pytest.mark.asyncio
@asyncio.coroutine
def test_allowed():
    from jenkins_epo.extensions.core import SecurityExtension

    ext = SecurityExtension('sec', Mock())
    ext.current = ext.bot.current
    ext.current.SETTINGS.COLLABORATORS = ['owner']
    ext.current.head.author = 'owner'
    ext.current.security_feedback_processed = None

    yield from ext.run()


@pytest.mark.asyncio
@asyncio.coroutine
def test_deny_and_comment():
    from jenkins_epo.extensions.core import SecurityExtension, SkipHead

    ext = SecurityExtension('sec', Mock())
    ext.current = ext.bot.current
    ext.current.head.author = 'untrusted'
    ext.current.security_feedback_processed = None
    ext.current.SETTINGS.COLLABORATORS = ['trusted']

    with pytest.raises(SkipHead):
        yield from ext.run()

    assert ext.current.head.comment.call_args_list


@pytest.mark.asyncio
@asyncio.coroutine
def test_deny_and_no_comment():
    from jenkins_epo.extensions.core import SecurityExtension, SkipHead

    ext = SecurityExtension('sec', Mock())
    ext.current = ext.bot.current
    ext.current.head.author = 'untrusted'
    ext.current.security_feedback_processed = True
    ext.current.SETTINGS.COLLABORATORS = ['trusted']

    with pytest.raises(SkipHead):
        yield from ext.run()

    assert not ext.current.head.comment.call_args_list
