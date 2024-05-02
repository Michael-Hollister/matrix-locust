#!/bin/env python3

import csv
import json
import logging
import resource

from locust import task, constant
from locust import events
from locust.runners import MasterRunner, WorkerRunner

import gevent
from matrix_locust.users.matrixuser import MatrixUser
from nio.responses import RoomCreateError, LoginError

# Preflight ####################################################################

@events.init.add_listener
def on_locust_init(environment, **_kwargs):
    # Increase resource limits to prevent OS running out of descriptors
    try:
        resource.setrlimit(resource.RLIMIT_NOFILE, (999999, 999999))
    except ValueError as e:
        logging.warning(f"Failed to increase the resource limit: {e}")

    # Multi-worker
    if isinstance(environment.runner, WorkerRunner):
        print(f"Registered 'load_users' handler on {environment.runner.client_id}")
        environment.runner.register_message("load_users", MatrixRoomCreatorUser.load_users)
    # Single-worker
    elif not isinstance(environment.runner, WorkerRunner) and not isinstance(environment.runner, MasterRunner):
        # Open our list of users
        MatrixRoomCreatorUser.worker_users = csv.DictReader(open("users.csv"))

@events.test_start.add_listener
def on_test_start(environment, **_kwargs):
    if not isinstance(environment.runner, MasterRunner):
        user_reader = csv.DictReader(open("users.csv", "r", encoding="utf-8"))

        # Load our list of rooms to be created
        logging.info("Loading rooms list")
        rooms = {}
        with open("rooms.json", "r", encoding="utf-8") as rooms_jsonfile:
            rooms = json.load(rooms_jsonfile)
        logging.info("Success loading rooms list")

        # Now we need to sort of invert the list
        # We need a list of the rooms to be created by each user,
        # with the list of other users who should be invited to each
        MatrixRoomCreatorUser.worker_rooms_for_users = {}
        for room_name, room_users in rooms.items():
            # Strip out domain from user entry if present
            first_user = room_users[0] if room_users[0].find(":") == -1 else room_users[0][:room_users[0].find(":")]
            user_rooms = MatrixRoomCreatorUser.worker_rooms_for_users.get(first_user, [])
            room_info = {
                "name": room_name,
                "users": room_users[1:]
            }
            user_rooms.append(room_info)
            MatrixRoomCreatorUser.worker_rooms_for_users[first_user] = user_rooms

###############################################################################


class MatrixRoomCreatorUser(MatrixUser):
    wait_time = constant(0)

    worker_id = None
    worker_users = []
    worker_rooms_for_users = {}

    @staticmethod
    def load_users(environment, msg, **_kwargs):
        MatrixRoomCreatorUser.worker_users = iter(msg.data)
        MatrixRoomCreatorUser.worker_id = environment.runner.client_id
        logging.info("Worker [%s]: Received %s users", environment.runner.client_id, len(msg.data))

    @task
    def create_rooms_for_user(self):
        # Multiple locust users re-use the same class instance, so need to reset the state
        self.reset_client()

        # Load the next user for room creation
        try:
            user = next(MatrixRoomCreatorUser.worker_users)
        except StopIteration:
            # We can't shut down the worker until all users are registered, so return
            # early to stop this individual co-routine
            gevent.sleep(999999)
            return

        self.login_from_csv(user)

        if self.matrix_client.user is None or self.matrix_client.password is None:
            logging.error("[%s]: Couldn't get username/password. Skipping...",
                          MatrixRoomCreatorUser.worker_id)
            return

        # Log in as this current user if not already logged in
        if self.matrix_client.user_id is None or self.matrix_client.access_token is None or \
            len(self.matrix_client.user_id) < 1 or len(self.matrix_client.access_token) < 1:

            response = self.matrix_client.login(self.matrix_client.password)

            if isinstance(response, LoginError):
                logging.error("Login failed for User [%s]", self.matrix_client.user)
                return

        def username_to_userid(username):
            user_id = username
            if not user_id.startswith("@"):
                user_id = "@" + username
            if ":" not in user_id:
                user_id += ":" + self.matrix_client.matrix_domain
            return user_id

        my_rooms_info = MatrixRoomCreatorUser.worker_rooms_for_users.get(self.matrix_client.user, [])
        #logging.info("User [%s] Found %d rooms to be created", self.username, len(my_rooms_info))

        for room_info in my_rooms_info:
            room_name = room_info["name"]
            #room_alias = room_name.lower().replace(" ", "-")
            usernames = room_info["users"]
            user_ids = list(map(username_to_userid, usernames))
            logging.info("User [%s] Creating room [%s] with %d users",
                         self.matrix_client.user, room_name, len(user_ids))

            # Actually create the room
            retries = 3
            while retries > 0:
                response = self.matrix_client.room_create(alias=None, name=room_name, invite=user_ids, federate=True)

                if isinstance(response, RoomCreateError):
                    logging.error("[%s] Could not create room %s (attempt %d). Trying again...",
                                 self.matrix_client.user, room_name, 4 - retries)
                    logging.error("[%s] Code=%s, Message=%s", self.matrix_client.user,
                                  response.status_code, response.message)
                    retries -= 1
                else:
                    logging.info("[%s] Created room [%s]", self.matrix_client.user, response.room_id)
                    break

            if retries == 0:
                logging.error("[%s] Error creating room %s. Skipping...",
                              self.matrix_client.user, room_name)