from importlib.metadata import packages_distributions, distribution
from packaging.utils import canonicalize_name

bonobo_packages = {}
for _pkg_name, _dist_names in packages_distributions().items():
    for _dist_name in _dist_names:
        _canon = canonicalize_name(_dist_name)
        if _canon.startswith("bonobo") and _canon not in bonobo_packages:
            bonobo_packages[_canon] = distribution(_dist_name)
