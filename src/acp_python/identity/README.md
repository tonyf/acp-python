# How should we handle on-behalf-of requests?

1. Multiple actors might communicate with each other on half of a user.
2. We need to be able to identify which actor is making the request and what permissions they have.
3. We need to be able to identify who the request is on behalf of so we pull the right data for that user.

## Potential Solutions

1. Central authority has a list of users, actors and their permissions for each user.
2. When an actor makes a request to another actor, it includes the user it is acting on behalf of by providing a user token that is specific to the user.
3. The receiving actor validates the user token and if valid, acts on behalf of the user.

Problem: the receive actor could be malicious and re-use the user token for its own purposes.

Solution: the user token is provided to the central authority and the actor requesting data needs to provide a key to the central authority to prove that it is the owner of the user token.

