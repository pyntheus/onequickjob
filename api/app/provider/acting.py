"""Who is using the provider app: the provider themself, or one of their helpers.

A helper is a user whose `helper_of` names the provider they help (decisions.md A17): the link
that lets the provider send them to visits, and nothing more. app.core.deps.current_provider
refuses helpers, so they can't accept jobs, suggest prices or decline for the provider (the shared
offer endpoints use it). Here a helper is recognised through helper_of, as long as the provider
still lists them (Provider.helpers, not removed).

Most of the app is the provider's own business (jobs, money, settings), so those endpoints take
`Owner` and refuse helpers; the round (today's visits, start, photos, finish) and documents take
`Acting`, and a helper sees and works only the visits they've been sent to.
"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, status

from app.core.db import Db, get_db
from app.core.deps import CurrentUser, current_user
from app.core.errors import fail
from app.models.providers import Helper, Provider
from app.repos.providers import Providers
from app.services.wording import first_name


@dataclass(frozen=True)
class Acting:
    provider: Provider
    cu: CurrentUser
    as_helper: Helper | None = None

    @property
    def helper(self) -> bool:
        return self.as_helper is not None

    @property
    def user_id(self) -> str:
        return self.cu.user.id


def _helper_entry(provider: Provider, user_id: str) -> Helper | None:
    return next((h for h in provider.helpers if h.user_id == user_id and h.status != "removed"), None)


async def acting_dep(cu: Annotated[CurrentUser, Depends(current_user)], db: Annotated[Db, Depends(get_db)]) -> Acting:
    providers = Providers(db)
    user = cu.user
    if "provider" in user.roles and not user.helper_of:
        provider = await providers.by_user(user.id)
        if provider is not None:
            return Acting(provider=provider, cu=cu)
    found = await providers.get(user.helper_of) if user.helper_of else None
    helper = _helper_entry(found, user.id) if found else None
    if found is None or helper is None:
        fail(status.HTTP_403_FORBIDDEN, "providers_only", "This is for providers. Sign up to earn with OneQuickJob.")
    return Acting(provider=found, cu=cu, as_helper=helper)


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
