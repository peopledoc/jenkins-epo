from unittest.mock import Mock


def test_write_comment():
    from jenkins_ghp.io import WriteComment

    io = WriteComment(body="Salve, munde!")
    io.run(Mock())
