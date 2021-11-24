import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from pprint import pformat
from typing import List, Optional, Union

import httpx

from pytest_zebrunner.api.models import (
    ArtifactReferenceModel,
    FinishTestModel,
    FinishTestSessionModel,
    LabelModel,
    LogRecordModel,
    RerunDataModel,
    StartTestModel,
    StartTestRunModel,
    StartTestSessionModel,
)
from pytest_zebrunner.context import zebrunner_context


class ZebrunnerAPI:
    authenticated = False

    def __init__(self, service_url: str = None, access_token: str = None):
        """
        Args:
            service_url (str): Url to access Zebrunner API. None by default.
            access_token (str): Access token to access Zebrunner API. None by default.
        """
        self.logger = logging.getLogger("zebrunner_client")
        self.logger.addHandler(logging.StreamHandler())
        self.logger.setLevel(zebrunner_context.settings.log_level_name)

        logging.DEBUG

        if service_url and access_token:
            self.service_url = service_url.rstrip("/")
            self.access_token = access_token
            self._client = httpx.Client()
            self._auth_token = None
            self.authenticated = False

    def log_response(self, response: httpx.Response, log_level: int = logging.DEBUG) -> None:
        """
        Logger customized configuration.
        """
        request = response.request
        request.read()

        self.logger.log(
            log_level,
            f"Request {request.method} {request.url}\n"
            f"Headers: \n{pformat(dict(request.headers))}\n\n"
            f"Content: \n{request.content}\n\n"
            f"Response Code: {response.status_code}\n"
            f" Content: \n{pformat(response.json())}",
        )

    def _sign_request(self, request: httpx.Request) -> httpx.Request:
        """
        Returns a request with the _auth_token set to the authorization request header.
        """
        request.headers["Authorization"] = f"Bearer {self._auth_token}"
        return request

    def _dispatch(self, request: httpx.Request) -> httpx.Response:
        """
        Send request to zebrunner and receive response.
        """
        try:
            return self._client.send(request)
        except httpx.ReadError as e:
            self.logger.error("Failed to send request to zebrunner", exc_info=e)

    def auth(self) -> None:
        """
        Validates the user access token with http post method and if it is correct, authenticates the user.
        """
        if not self.access_token or not self.service_url:
            return

        url = self.service_url + "/api/iam/v1/auth/refresh"
        response = self._dispatch(httpx.Request("POST", url, json={"refreshToken": self.access_token}))

        if response.status_code != 200:
            self.log_response(response, logging.ERROR)
            return

        self._auth_token = response.json()["authToken"]
        self._client.auth = self._sign_request
        self.authenticated = True

    def start_test_run(self, project_key: str, body: StartTestRunModel) -> Optional[int]:
        """
        Sends request to zebrunner, to start test-run.

        Returns:
            Optional[int]: Returns id of test-run if it successfully started otherwise returns None
        """
        url = self.service_url + "/api/reporting/v1/test-runs"
        req = httpx.Request(
            "POST", url, params={"projectKey": project_key}, json=body.dict(exclude_none=True, by_alias=True)
        )
        response = self._dispatch(req)

        if response.status_code != 200:
            self.log_response(response, logging.ERROR)
            return None

        return response.json()["id"]

    def start_test(self, test_run_id: int, body: StartTestModel) -> Optional[int]:
        """
        Sends request to zebrunner to start test
        """
        url = self.service_url + f"/api/reporting/v1/test-runs/{test_run_id}/tests"

        response = self._dispatch(httpx.Request("POST", url, json=body.dict(exclude_none=True, by_alias=True)))

        if response.status_code != 200:
            self.log_response(response, logging.ERROR)
            return None

        return response.json()["id"]

    def finish_test(self, test_run_id: int, test_id: int, body: FinishTestModel) -> None:
        """
        Execute an http put with the given test_run_id, test_id, and body, which contains FinishTestModel.
        If everything is OK, finish the Test. Otherwise, logs errors.

        Args:
            test_run_id (int): Number that identifies test_run.
            test_id (int): Number that identifies test.
            body (FinishTestModel): Entity with FinishTest properties.

        """
        url = self.service_url + f"/api/reporting/v1/test-runs/{test_run_id}/tests/{test_id}"

        try:
            response = self._client.put(url, json=body.dict(exclude_none=True, by_alias=True))
        except httpx.RequestError as e:
            self.logger.warning("Error while sending request to zebrunner.", exc_info=e)
            return

        if response.status_code != 200:
            self.log_response(response, logging.ERROR)

    def finish_test_run(self, test_run_id: int) -> None:
        """
        Execute an http put with the given test_run_id.
        If everything is OK, updates endedAt value finishing test_run. Otherwise, logs errors.

        Args:
            test_run_id (int): Number that identifies test_run.
        """
        url = self.service_url + f"/api/reporting/v1/test-runs/{test_run_id}"
        response = self._dispatch(
            httpx.Request(
                "PUT",
                url,
                json={"endedAt": (datetime.utcnow().replace(tzinfo=timezone.utc) - timedelta(seconds=1)).isoformat()},
            )
        )

        if response.status_code != 200:
            self.log_response(response, logging.ERROR)
            return

    def send_logs(self, test_run_id: int, logs: List[LogRecordModel]) -> None:
        """
        Push collected logs to zebrunner

        Args:
            test_run_id (int): Zebrunner id of test-run.
            logs (List[LogRecordModel]): Logs received by logging handler
        """
        url = self.service_url + f"/api/reporting/v1/test-runs/{test_run_id}/logs"

        body = [x.dict(exclude_none=True, by_alias=True) for x in logs]
        self._dispatch(httpx.Request("POST", url, json=body))

    def send_screenshot(self, test_run_id: int, test_id: int, image_path: Union[str, Path]) -> None:
        """
        Sends content of image from disk to zebrunner

        Args:
            test_run_id (int): Zebrunner id of test-run
            test_id (int): Zebrunner id of test
            image_path (Union[str,Path)]: Path to image location

        Raises:
            FileNotFoundError: If screenshot file is not reachable.

        """
        url = self.service_url + f"/api/reporting/v1/test-runs/{test_run_id}/tests/{test_id}/screenshots"
        with open(image_path, "rb") as image:
            self._dispatch(
                httpx.Request(
                    "POST",
                    url,
                    content=image.read(),
                    headers={"Content-Type": "image/png", "x-zbr-screenshot-captured-at": round(time.time() * 1000)},
                )
            )

    def send_artifact(self, filename: Union[str, Path], test_run_id: int, test_id: Optional[int] = None) -> None:
        """
        Sends file content from disk to zebrunner and attaches it to test if test-run id and test-id provided
        otherwise attach it to test-run.

        Args:
            filename (Union[str, Path]): Path to file location
            test_run_id (int): Zebrunner id of test-run.
            test_id: (int, optional): `Zebrunner id of test.

        Raises:
            FileNotFoundError: If artifact file is not reachable.

        """
        if test_id:
            url = f"{self.service_url}/api/reporting/v1/test-runs/{test_run_id}/tests/{test_id}/artifacts"
        else:
            url = f"{self.service_url}/api/reporting/v1/test-runs/{test_run_id}/artifacts"
        with open(filename, "rb") as file:
            self._dispatch(request=httpx.Request("POST", url, files={"file": file}))

    def send_artifact_references(
        self, references: List[ArtifactReferenceModel], test_run_id: int, test_id: Optional[int] = None
    ) -> None:
        """
        Sends artifact-references to zebrunner and attaches it to test if test-id provided
        otherwite attaches it to test-run.

        Args:
            references (List[ArtifactReferenceModel]): List of artifacts references to send to  reporting.
            test_run_id (int): Zebrunner test-run id.
            test_id: (int, optional): Zebrunner test id.
        """
        if test_id:
            url = f"{self.service_url}/api/reporting/v1/test-runs/{test_run_id}/tests/{test_id}/artifact-references"
        else:
            url = f"{self.service_url}/api/reporting/v1/test-runs/{test_run_id}/artifact-references/"
        json_items = [item.dict(exclude_none=True, by_alias=True) for item in references]
        self._dispatch(httpx.Request("PUT", url, json={"items": json_items}))

    def send_labels(self, labels: List[LabelModel], test_run_id: int, test_id: Optional[int] = None) -> None:
        """
        Sends labels to zebrunner and attaches it to test if test-id provided otherwite attaches it to test-run.

        Args:
            labels (List[LabelModel]): List of labels to send for reporting.
            test_run_id (int): Zebrunner id of test-run.
            test_id: (optional int): Zebrunner id of test.

        """
        if test_id:
            url = f"{self.service_url}/api/reporting/v1/test-runs/{test_run_id}/tests/{test_id}/labels"
        else:
            url = f"{self.service_url}/api/reporting/v1/test-runs/{test_run_id}/labels"
        labels_json = [label.dict(exclude_none=True, by_alias=True) for label in labels]
        self._dispatch(httpx.Request("PUT", url, json={"items": labels_json}))

    def start_test_session(self, test_run_id: int, body: StartTestSessionModel) -> Optional[str]:
        """
        Send selenium session details to zebrunner

        Args:
            test_run_id (int): Zebrunner id of test-run
            body (StartTestSessionModel):

        Returns:
            Optional[str]: Zebrunner id of session if response was successfull otherwise returns None
        """
        url = self.service_url + f"/api/reporting/v1/test-runs/{test_run_id}/test-sessions"
        response = self._dispatch(httpx.request("POST", url, json=body.dict(exclude_none=True, by_alias=True)))
        if not response.status_code == 200:
            self.log_response(response, logging.ERROR)
            return None

        return response.json().get("id")

    def finish_test_session(self, test_run_id: int, zebrunner_id: str, body: FinishTestSessionModel) -> None:
        """
        Send selenium session finish event to zebrunner.

        Args:
            test_run_id (int): Zebrunner id of test-run.
            zebrunner_id (str): Zebrunner id of selenium session.
        """
        url = self.service_url + f"/api/reporting/v1/test-runs/{test_run_id}/test-sessions/{zebrunner_id}"
        self._dispatch(httpx.Request("PUT", url, json=body.dict(exclude_none=True, by_alias=True)))

    def get_rerun_tests(self, run_context: str) -> RerunDataModel:
        """
        Gets run_context and list of tests to rerun in run triggered from zebrunner launcher.
        """
        url = self.service_url + "/api/reporting/v1/run-context-exchanges"
        run_context_dict = json.loads(run_context)
        response = self._dispatch(httpx.Request("POST", url, json=run_context_dict))
        response_data = response.json()
        for test in response_data["tests"]:
            correlation_data = test["correlationData"]
            if correlation_data is not None:
                test["correlationData"] = json.loads(correlation_data)
        return RerunDataModel(**response_data)

    def close(self) -> None:
        """
        Close the connection pool without block-usage.
        """
        self._client.close()
