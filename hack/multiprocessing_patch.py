# Patch Lock class in AWS Lambda environment

class Lock:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        pass

    def __exit__(self, type, value, traceback):
        pass

    def acquire(self, *args, **kwargs):
        pass

    def release(self):
        pass


class RLock(Lock):
    pass


# Ensure the original Lock isn't imported by adding:
Lock = Lock
RLock = RLock
