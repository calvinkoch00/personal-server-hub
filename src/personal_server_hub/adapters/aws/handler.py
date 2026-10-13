from personal_server_hub.adapters.aws.router import route_request

def lambda_handler(event, context):
    return route_request(event, context)