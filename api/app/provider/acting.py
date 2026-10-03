"""Who is using the provider app: the provider themself, or one of their helpers.

app.core.deps.current_provider gives a helper their provider's context. Most of the app is
the provider's own business (jobs, money, settings), so those endpoints take `Owner` and
refuse helpers; the round (today's visits, start, photos, finish) takes `Acting`, and a
helper sees and works only the visits they've been sent to.
"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, status

from app.core.deps import CurrentUser, current_provider, current_user
from app.core.errors import fail
from app.models.providers import Provider
from app.services.wording import first_name


@dataclass(frozen=True)
class Acting:
    provider: Provider
    cu: CurrentUser

    @property
    def helper(self) -> bool:
        return bool(self.cu.user.helper_of)

    @property
    def user_id(self) -> str:
        return self.cu.user.id


async def acting_dep(
    cu: Annotated[CurrentUser, Depends(current_user)], provider: Annotated[Provider, Depends(current_provider)]
) -> Acting:
    return Acting(provider=provider, cu=cu)


def require_owner(a: Acting) -> Provider:
    if a.helper:
        fail(
            status.HTTP_403_FORBIDDEN,
            "helpers_cant",
            f"This part of the app is for {first_name(a.provider.name)}. You can see your visits on Today.",
        )
    return a.provider


async def owner_dep(a: Annotated[Acting, Depends(acting_dep)]) -> Provider:
    return require_owner(a)


Act = Annotated[Acting, Depends(acting_dep)]
Owner = Annotated[Provider, Depends(owner_dep)]
