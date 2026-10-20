"""The kit's errors: the only ones a host layer raises, and the ones every kit verb answers.

`HostError` is "a verb cannot finish": its message is the ONE line the caller prints, and
`status` is the host's own status (an HTTP code) when there was one. Four failures have a
class of their own, because a requirement, a login row or a flow answers them differently:

- `Missing`: the host's tool is not on this machine;
- `SignedOut`: there is no sign-in the host accepts;
- `NotFound`: the host says there is no such thing, or none this account may see;
- `OutsideChange`: a review's finding is on a line the change does not touch, so the review
  was not posted as written, by the host's refusal or the layer's own look at the change (the
  kit then posts it again with every finding in its body).

A pack's own error classes subclass these and may keep their old names.
"""


class HostError(Exception):
    """A verb cannot finish; the message is the one line the caller prints."""

    status: int | None = None


class Missing(HostError):
    """The host's tool is not on this machine's path."""


class SignedOut(HostError):
    """There is no sign-in the host accepts."""


class NotFound(HostError):
    """The host says what was asked for does not exist, or is not visible to this account."""


class OutsideChange(HostError):
    """A review was not posted because a finding is on a line outside the change."""
