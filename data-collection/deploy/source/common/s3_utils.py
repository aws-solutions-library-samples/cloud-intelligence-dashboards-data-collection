"""
CID S3 Utilities

Generic S3 bucket helpers: parsing a bucket name out of an ``s3://`` URL or a
virtual-hosted S3 domain, and reading a bucket's region, tags, and lifecycle
configuration. Every method takes the specific value it needs (a client, a
bucket name, a URL) rather than a collector context, so this has no
dependency on the collection framework and can be used from any module, or a
plain script.
"""

from urllib.parse import urlparse

from botocore.exceptions import ClientError


class S3Utils:
    """Stateless S3 bucket helpers. All methods are static."""

    @staticmethod
    def bucket_from_url(url) -> str:
        """Extract an S3 bucket name from an ``s3://`` or virtual-hosted URL.

        Args:
            url: A URL that may address an S3 bucket.

        Returns:
            str: The bucket name, or ``""``.
        """
        if not url:
            return ""
        text = str(url)
        if text.startswith("s3://") or text.startswith("s3ssl://"):
            return text.split("//", 1)[1].split("/", 1)[0]
        try:
            hostname = (urlparse(text).hostname or "").lower()
        except ValueError:
            hostname = ""
        return S3Utils.bucket_from_domain(hostname)

    @staticmethod
    def bucket_from_domain(domain) -> str:
        """Extract an S3 bucket name from a virtual-hosted S3 domain name.

        Args:
            domain: A hostname such as ``my-bucket.s3.us-east-1.amazonaws.com``.

        Returns:
            str: The bucket name, or ``""``.
        """
        domain = (domain or "").lower()
        if ".s3" not in domain or not domain.endswith("amazonaws.com"):
            return ""
        return domain.split(".s3", 1)[0]

    @staticmethod
    def bucket_region(client, name) -> str:
        """Return a bucket's region, or ``""`` if it cannot be determined.

        Args:
            client: An S3 client.
            name: Bucket name.
        """
        try:
            constraint = client.get_bucket_location(Bucket=name).get("LocationConstraint")
        except ClientError:
            return ""
        if not constraint:
            return "us-east-1"
        return "eu-west-1" if constraint == "EU" else constraint

    @staticmethod
    def bucket_tags(client, name) -> list:
        """Return a bucket's tags, or ``[]`` when it has none.

        Args:
            client: An S3 client.
            name: Bucket name.
        """
        try:
            return client.get_bucket_tagging(Bucket=name).get("TagSet", [])
        except ClientError:
            return []

    @staticmethod
    def bucket_lifecycle_rules(client, name) -> list:
        """Return a bucket's lifecycle rules, or ``[]`` when it has none.

        Args:
            client: An S3 client.
            name: Bucket name.
        """
        try:
            return client.get_bucket_lifecycle_configuration(Bucket=name).get("Rules", [])
        except ClientError:
            return []

    @staticmethod
    def lifecycle_storage_classes(rules) -> list:
        """List the storage classes a bucket's lifecycle rules transition into.

        Args:
            rules: Lifecycle rules from :meth:`bucket_lifecycle_rules`.

        Returns:
            list: Distinct storage class names, sorted.
        """
        classes = set()
        for rule in rules:
            for transition in rule.get("Transitions", []):
                if transition.get("StorageClass"):
                    classes.add(transition["StorageClass"])
            for transition in rule.get("NoncurrentVersionTransitions", []):
                if transition.get("StorageClass"):
                    classes.add(transition["StorageClass"])
        return sorted(classes)
