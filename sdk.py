import grpc
import json
import sdk_pb2
import sdk_pb2_grpc

from google.protobuf import empty_pb2
from typing import TypedDict, List


class CafeSDK:
    _channel = grpc.insecure_channel("127.0.0.1:20086")

    class _ParameterService:
        def __init__(self, channel):
            self.stub = sdk_pb2_grpc.ParameterStub(channel)

        def get_input_json_str(self):
            resp = self.stub.GetInputJSONString(empty_pb2.Empty())
            return resp.jsonString

        def get_input_json_dict(self):
            json_str = self.get_input_json_str()
            return json.loads(json_str) if json_str else {}

    class _ResultService:
        def __init__(self, channel):
            self.stub = sdk_pb2_grpc.ResultStub(channel)

        class TableHeader(TypedDict):
            label: str
            key: str
            format: str

        def set_table_header(self, headers: List[TableHeader]):
            # Build TableHeaderItem for each header (protobuf repeated message)
            items = [
                sdk_pb2.TableHeaderItem(label=h["label"], key=h["key"], format=h["format"])
                for h in headers
            ]
            msg = sdk_pb2.TableHeader(headers=items)
            return self.stub.SetTableHeader(msg)

        def push_data(self, dict_obj):
            json_str = json.dumps(dict_obj, ensure_ascii=False)
            data = sdk_pb2.Data(jsonString=json_str)
            return self.stub.PushData(data)

    class _LogService:
        def __init__(self, channel):
            self.stub = sdk_pb2_grpc.LogStub(channel)

        def debug(self, log: str):
            return self.stub.Debug(sdk_pb2.LogBody(log=log))

        def info(self, log: str):
            return self.stub.Info(sdk_pb2.LogBody(log=log))

        def warn(self, log: str):
            return self.stub.Warn(sdk_pb2.LogBody(log=log))

        def error(self, log: str):
            return self.stub.Error(sdk_pb2.LogBody(log=log))

    Parameter = _ParameterService(_channel)
    Result = _ResultService(_channel)
    Log = _LogService(_channel)
