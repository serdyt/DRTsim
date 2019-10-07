class OTPException(Exception):
    def __init__(self, msg, original_exception):
        super(OTPException, self).__init__(msg + (": %s" % original_exception))
        self.original_exception = original_exception


class OTPError(Exception):
    def __init__(self, msg, context=None):
        super(OTPError, self).__init__(msg)
        self.msg = msg
        self.context = context


class OTPTrivialPath(OTPError):
    def __init__(self, msg, context=None):
        super(OTPTrivialPath, self).__init__(msg, context)


class OTPNoPath(OTPError):
    def __init__(self, msg, context=None):
        super(OTPNoPath, self).__init__(msg, context)


class OTPUnreachable(OTPError):
    def __init__(self, msg, context=None):
        super(OTPUnreachable, self).__init__(msg, context)


class OTPGeneralRouting(OTPError):
    def __init__(self, msg, context=None):
        super(OTPGeneralRouting, self).__init__(msg, context)
