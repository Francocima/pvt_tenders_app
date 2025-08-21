import boto3

do_spaces_config = {
    "region": "syd1",
    "endpoint_url": "https://syd1.digitaloceanspaces.com",
    "access_key": "DO8019DEAMD4HNJXLCM3",
    "secret_key": "oaZQ3iso/NNJWDbhLCb4b4mndshB4eRG5Ulsjtx+VpE",
    "bucket_name": "tenders"
}

try:
    session = boto3.session.Session()
    client = session.client(
        service_name='s3',
        region_name=do_spaces_config['region'],
        endpoint_url=do_spaces_config['endpoint_url'],
        aws_access_key_id=do_spaces_config['access_key'],
        aws_secret_access_key=do_spaces_config['secret_key']
    )

    # Test connection by listing objects
    response = client.list_objects_v2(Bucket=do_spaces_config['bucket_name'])
    print("Connected successfully! Object list:")
    print(response.get('Contents', []))

except Exception as e:
    print("Failed to connect:", str(e))