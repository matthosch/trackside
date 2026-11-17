"""Stock photos for synthetic stays, hotlinked from Unsplash.

Chosen from Unsplash's free-licence results for "modern house", "sports car house",
and "sports car hotel". Images are served from Unsplash's CDN, not copied here, and
each one is credited to its photographer where it is shown.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Photo:
    photo_id: str  # Unsplash photo page id
    image: str  # CDN image key
    username: str  # photographer's Unsplash handle
    category: str  # "house" or "hotel"

    @property
    def url(self) -> str:
        return f"https://images.unsplash.com/photo-{self.image}"

    @property
    def page(self) -> str:
        return f"https://unsplash.com/photos/{self.photo_id}"


PHOTOS = [
    # "modern house"
    Photo("3ddHcjHmiGw", "1721815693498-cc28507c0ba2", "nakshabanwao", "house"),
    Photo("_TPTXZd9mOo", "1580587771525-78b9dba3b914", "webaliser", "house"),
    Photo("ylzGfY-xzBY", "1783125127199-860da9744dcc", "salvomedia", "house"),
    Photo("hHz4yrvxwlA", "1613490493576-7fde63acd811", "aviwerde", "house"),
    Photo("eWOgoFHlE8g", "1758448756207-54505680d130", "aalolens", "house"),
    Photo("z6UAWpQAhXs", "1670589953882-b94c9cb380f5", "salmansaqib", "house"),
    Photo("4vioYQ9Nn9Y", "1748063578185-3d68121b11ff", "bipow", "house"),
    Photo("P21wf6KAykw", "1628012209120-d9db7abf7eab", "felifox", "house"),
    Photo("mR1CIDduGLc", "1600596542815-ffad4c1539a9", "framesforyourheart", "house"),
    Photo("WaC-JFfF21M", "1706808849780-7a04fbac83ef", "salmansaqib", "house"),
    Photo("Id7u0EkTjBE", "1613977257363-707ba9348227", "johnfo", "house"),
    # "sports car house"
    Photo("wwlM4ZPyifY", "1562596133-06ae520e8c7e", "visualsbyroyalz", "house"),
    Photo("Xxq6gXo2k38", "1665691964802-956fc06b93cf", "petrokas", "house"),
    Photo("5r4ABMjnjXk", "1604497852413-fdba42621f9c", "jaquestories", "house"),
    Photo("TwDWlhvocew", "1741231785368-8ca541d9e2f5", "cpantoni", "house"),
    Photo("fHsZSZ31Sa0", "1793531113059-6d836ce130d3", "hypernature", "house"),
    Photo("5jJixReBwxw", "1690406493967-4ca15c6ba09a", "t_ahmetler", "house"),
    Photo("UKR7CZxZKhA", "1728287715124-b5eb0bd0c0b8", "brechtdenil", "house"),
    Photo("bcIs3MD8mjk", "1680943100828-95bf530110e6", "tony_saiko24", "house"),
    # "sports car hotel"
    Photo("izJMBRHemi8", "1678126581951-9e740e7104d0", "photobycarl", "hotel"),
    Photo("uJMHs3BmgLQ", "1777997916954-c1ced36ea4e7", "albertocognetti", "hotel"),
    Photo("gXwarBSTUQc", "1767978671049-92d02fe8597c", "rm_reins", "hotel"),
    Photo("E4AUjCVzznA", "1780945008795-f655806f0806", "poli_graphy", "hotel"),
    Photo("kqqDYzL6kUo", "1780945010244-00fa84ea5bb5", "poli_graphy", "hotel"),
    Photo("51pqWTiEInE", "1788982201284-5e868780f38a", "nathanvandenheuvel", "hotel"),
]
