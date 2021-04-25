import logging
from typing import Union

import pytest
from _pytest.config import ExitCode
from _pytest.main import Session
from _pytest.nodes import Item
from _pytest.reports import TestReport
from _pytest.runner import CallInfo

from pytest_zebrunner.context import zebrunner_context
from pytest_zebrunner.reporting_service import ReportingService
from pytest_zebrunner.selenium_integration import SeleniumSession, inject_driver

logger = logging.getLogger(__name__)


class PytestZebrunnerHooks:
    def __init__(self) -> None:
        self.service = ReportingService()
        self.session_manager = SeleniumSession(self.service)

    @pytest.hookimpl
    def pytest_sessionstart(self, session: Session) -> None:
        self.service.start_test_run()
        inject_driver(self.session_manager)

    @pytest.hookimpl
    def pytest_sessionfinish(self, session: Session, exitstatus: Union[int, ExitCode]) -> None:
        self.service.finish_test_run()
        self.session_manager.finish_all_sessions()

    @pytest.hookimpl
    def pytest_runtest_makereport(self, item: Item, call: CallInfo) -> TestReport:
        report = TestReport.from_item_and_call(item, call)
        if report.when == "setup":
            self.service.start_test(report, item)
        elif report.when == "call":
            if zebrunner_context.test_is_active:
                self.session_manager.add_test(zebrunner_context.test_id)
            self.service.finish_test(report, item)
        return report

    # @pytest.hookimpl
    # def pytest_report_teststatus(self, report: TestReport, config: Config) -> None:
    #     if self.is_worker:
    #         zebrunner_context.test_run.zebrunner_id = config.workerinput["test_run_id"]  # type: ignore

    #     if report.when == "setup":
    #         self.setup_test(report)
    #     elif report.when == "call":
    #         self.call_test(report)
