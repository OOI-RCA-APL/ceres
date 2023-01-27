import re
from typing import TYPE_CHECKING

NAME_REGEX = re.compile(r"^[a-zA-Z_\-][a-zA-Z0-9_\-]*$")

if TYPE_CHECKING:
    Name = str
else:
    from pydantic import ConstrainedStr

    class Name(ConstrainedStr):
        regex = NAME_REGEX
