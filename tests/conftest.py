from libfaketime import reexec_if_needed


def pytest_configure():
    reexec_if_needed()
