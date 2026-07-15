# 原始数据集格式备忘

## 路径约定

原始数据集按训练集和验证集拆分：

```text
datasets/
  train/
    xxx.json
  val/
    xxx.json
```

常用路径样例：

```text
datasets/train/
datasets/val/
```

每个 JSON 文件表示一张网络拓扑图。

## 顶层结构

```json
{
  "directed": false,
  "multigraph": false,
  "deviceGroups": [],
  "nodes": [],
  "links": []
}
```

字段说明：

- `directed`: 是否有向图。
- `multigraph`: 是否多重图。
- `deviceGroups`: 设备组级别信息和配置。
- `nodes`: 节点级别信息和配置。
- `links`: 节点之间的连接关系。

## deviceGroups 结构

```json
{
  "deviceGroup": {
    "NAME": "",
    "DEVICEGROUPTYPES": "AP"
  },
  "configs": [
    {
      "ap-psk": {
        "tunnel-encrypt": true
      }
    },
    {
      "zone-info": {
        "zone-sn": ""
      }
    }
  ]
}
```

注意：

- 设备组配置字段是 `configs`。
- `configs` 是列表。
- 每个配置对象通常只有一个顶层 key，例如 `ap-psk`、`zone-info`。

## nodes 结构

```json
{
  "id": "NODE_1",
  "devices": {
    "NAME": "",
    "MANUFACTURER": "",
    "MODEL": "",
    "TYPE": "",
    "SOFTWARE_VERSION": "",
    "NET_ENVIRONMENT": 0,
    "APTYPE": "",
    "SUBTYPE": ""
  },
  "topologyNode": {
    "NODECLASS": "",
    "DEVICEROLE": "",
    "CLASSNAME": ""
  },
  "config": [
    {
      "cloud-ap-interfaces": {
        "cloud-ap-interface": []
      }
    }
  ]
}
```

注意：

- 节点唯一标识是 `id`，例如 `NODE_1`。
- 设备属性历史样例中是 `devices`。
- agent provider 文档里也出现过 `device`，因此代码里建议兼容 `device` 和 `devices`。
- 节点配置字段历史上可能是 `config`，也可能是 `configs`，后续处理节点配置时建议同时兼容。
- `topologyNode.DEVICEROLE` 表示节点角色。如果转换到标准 schema 的 `roles`，字符串需要转成列表。

## links 结构

```json
{
  "source": "NODE_1",
  "target": "NODE_2",
  "link": {
    "LEFTPORT": "",
    "RIGHTPORT": "",
    "LABEL": "",
    "CLASSNAME": ""
  }
}
```

注意：

- `source` 和 `target` 位于 link 对象顶层。
- `source`、`target` 对应 `nodes[].id`。
- 端口信息在 `link.LEFTPORT` 和 `link.RIGHTPORT`。
- 链路名称通常使用 `link.LABEL`。

## 配置生成任务约定

最终任务是配置生成：

- node 配置来自 `nodes[].config` 或 `nodes[].configs`。
- device group 配置来自 `deviceGroups[].configs`。
- 每次样本通常只遮挡一个配置对象的一个顶层 key。
- 目标输出仍保持完整 `{top_level_key: value}` 形式。
- 例如顶层 key：
  - `cloud-ap-interfaces`
  - `apstormsuppression-business`
  - `ap-psk`
  - `zone-info`

