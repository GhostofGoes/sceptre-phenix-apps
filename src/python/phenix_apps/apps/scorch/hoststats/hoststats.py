import json
import signal
import threading
import time

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common.logger import logger


class HostStats(ComponentBase):
    def __init__(self):
        self._stopping = threading.Event()

        ComponentBase.__init__(self, "hoststats")

        # phenix stops a background component with SIGTERM and kills it 10 s
        # later, so the handler wakes the monitor from its poll wait at once.
        # It replaces the one ComponentBase installs for a background start,
        # which ignores SIGTERM, before anything else runs, so that a SIGTERM
        # that arrives before start is not lost. The thread that runs start
        # only joins the monitor and never takes the event's lock itself, so
        # the handler cannot deadlock on it.
        if self.stage == "start" and self.is_background():
            signal.signal(signal.SIGTERM, lambda *_: self._stopping.set())

        self.poll_period = self.metadata.get("pollPeriod", 5)
        self.flush_period = self.metadata.get("flushPeriod", None)

        if self.flush_period is None or self.flush_period < self.poll_period:
            self.flush_period = self.poll_period

        self.resdata = []
        self._monitor_error: Exception | None = None

        self.execute_stage()

    def start(self):
        logger.info(f"Starting user component: {self.name}")

        # start waits for the SIGTERM phenix sends only to background
        # components, so in the foreground it would block the pipeline forever.
        if not self.is_background():
            raise ValueError(
                f"hoststats component '{self.name}' must set background: true; "
                "its start stage runs until phenix stops it"
            )

        thread = threading.Thread(target=self.__run_monitor)
        thread.start()

        logger.info(f"Started user component: {self.name}")

        thread.join()

        logger.info(f"Stopping user component: {self.name}")

        self.__flush_buffer()

        if self._monitor_error is not None:
            raise RuntimeError(
                f"hoststats component '{self.name}' stopped polling minimega: "
                f"{self._monitor_error}"
            ) from self._monitor_error

        logger.info(f"Stopped user component: {self.name}")

    def __run_monitor(self):
        count = 0

        try:
            while not self._stopping.is_set():
                data = self.__get_resdata()

                if data:
                    self.resdata.extend(data)

                if count % int(self.flush_period / self.poll_period) == 0:
                    self.__flush_buffer()

                self._stopping.wait(self.poll_period)
                count += 1
        except Exception as ex:
            self._monitor_error = ex

    def __flush_buffer(self):
        if not self.resdata:
            return

        output_file = self.base_dir / "host_stats.jsonl"

        # write jsonl
        with output_file.open("a+") as f:
            for datum in self.resdata:
                json_record = json.dumps(datum)
                f.write(json_record + "\n")

        # clear buffer
        self.resdata = []

    def __get_resdata(self):
        resdata = []
        host_vms = {}
        vm_info = self.mm.vm_info()

        try:
            for host in vm_info:
                name_indx = host["Header"].index("name")
                host_vms[host["Host"]] = []

                for vm in host["Tabular"]:
                    host_vms[host["Host"]].append(vm[name_indx])
        except TypeError:
            pass

        host_info = self.mm.host()

        logger.info(f"getting host data for {len(vm_info)} hosts")
        try:
            for host in host_info:
                host_dict = {}

                host_dict["compute_name"] = host["Data"].pop("Name")
                host_dict.update(host["Data"])

                loads = host_dict.pop("Load").split()

                host_dict["Load_1"] = float(loads[0])
                host_dict["Load_5"] = float(loads[1])
                host_dict["Load_15"] = float(loads[2])

                host_dict["timestamp"] = int(time.time() * 1000)  # milliseconds
                host_dict["vm_list"] = sorted(
                    host_vms.get(host_dict["compute_name"], [])
                )

                resdata.append(host_dict)
        except TypeError:
            return []

        # print current data so users can see it in UI modal in real-time
        logger.info(resdata)
        return resdata


def main():
    HostStats()


if __name__ == "__main__":
    main()
