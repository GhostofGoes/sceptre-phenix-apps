package main

import (
	"bytes"
	"encoding/json"
	"log/slog"
	"path/filepath"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestFilterVMs(t *testing.T) {
	t.Parallel()

	var (
		log = slog.Default()
		vms = []string{"vm1", "router1", "vm2", "firewall1"}
	)

	getNodeType := func(name string) string {
		switch name {
		case "router1":
			return "router"
		case "firewall1":
			return "firewall"
		default:
			return "vm"
		}
	}

	tests := []struct {
		name     string
		hmd      MirrorHostMetadata
		expected []string
	}{
		{
			name:     "single vlan",
			hmd:      testMetadata([]string{"100"}, false),
			expected: []string{"vm1", "router1", "vm2", "firewall1"},
		},
		{
			name:     "multiple vlans, no mirror routed",
			hmd:      testMetadata([]string{"100", "101"}, false),
			expected: []string{"vm1", "vm2"},
		},
		{
			name:     "multiple vlans, mirror routed",
			hmd:      testMetadata([]string{"100", "101"}, true),
			expected: []string{"vm1", "router1", "vm2", "firewall1"},
		},
		{
			name:     "empty vms",
			hmd:      testMetadata([]string{"100", "101"}, false),
			expected: []string{},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()

			var inputVMs []string
			if tt.name != "empty vms" {
				inputVMs = make([]string, len(vms))
				copy(inputVMs, vms)
			}

			got := filterVMs(log, inputVMs, tt.hmd, "target", getNodeType)
			assert.Equal(t, tt.expected, got)
		})
	}
}

func TestFilterVMs_CaseInsensitive(t *testing.T) {
	t.Parallel()

	log := slog.Default()
	vms := []string{"ROUTER1"}
	hmd := testMetadata([]string{"1", "2"}, false)

	getNodeType := func(_ string) string {
		return "ROUTER"
	}

	got := filterVMs(log, vms, hmd, "target", getNodeType)
	assert.Empty(t, got, "Should filter out ROUTER (case insensitive)")
}

func testMetadata(vlans []string, routed bool) MirrorHostMetadata {
	return MirrorHostMetadata{
		Interface:    "",
		VLANs:        vlans,
		HIL:          nil,
		SetupOVS:     false,
		MirrorRouted: routed,
	}
}

func TestRunRejectsAWrongArgumentCount(t *testing.T) {
	t.Parallel()

	for _, args := range [][]string{nil, {"configure", "cleanup"}} {
		var stdout bytes.Buffer

		err := run(testLogger(), args, strings.NewReader(""), &stdout)
		require.ErrorContains(t, err, "expected one argument, the stage")
		assert.Empty(t, stdout.String(), "args %v", args)
	}
}

func TestRunRejectsAnUnknownStage(t *testing.T) {
	testEnv(t, false)

	var stdout bytes.Buffer

	err := run(testLogger(), []string{"post_start"}, testInput(t, testExperiment(t, nil, nil)), &stdout)
	require.ErrorContains(t, err, `unknown stage "post_start", want configure, pre-start,`)
	assert.Empty(t, stdout.String())
}

func TestRunPassesTheExperimentThroughTheRunningStage(t *testing.T) {
	testEnv(t, false)

	body, err := json.Marshal(testExperiment(t, nil, nil))
	require.NoError(t, err)

	var stdout bytes.Buffer

	require.NoError(t, run(testLogger(), []string{"running"}, bytes.NewReader(body), &stdout))
	assert.Equal(t, string(body), stdout.String())
}

func TestRunRejectsStdinThatIsNotAnExperiment(t *testing.T) {
	t.Parallel()

	var stdout bytes.Buffer

	err := run(testLogger(), []string{"configure"}, strings.NewReader("this is not an experiment\n"), &stdout)
	require.ErrorContains(t, err, "decoding experiment from stdin")
	assert.Empty(t, stdout.String())
}

func TestRunFailsAFailingStageWithoutPrintingTheExperiment(t *testing.T) {
	testEnv(t, true)

	md := map[string]any{"version": "v1", "erspan": map[string]any{"enabled": true, "version": 3}}

	var stdout bytes.Buffer

	err := run(testLogger(), []string{"post-start"}, testInput(t, testExperiment(t, md, nil)), &stdout)
	require.ErrorContains(t, err, "executing post-start stage: unknown ERSPAN version (3) configured for monh")
	assert.Empty(t, stdout.String())
}

func TestCleanupWithoutMirrorStatusSucceeds(t *testing.T) {
	testEnv(t, false)

	var stdout bytes.Buffer

	err := run(testLogger(), []string{"cleanup"}, testInput(t, testExperiment(t, nil, nil)), &stdout)
	require.NoError(t, err)

	var out map[string]any

	require.NoError(t, json.Unmarshal(stdout.Bytes(), &out))
	assert.Equal(t, "exp1", out["spec"].(map[string]any)["experimentName"])
}

func TestCleanupRejectsAMalformedMirrorStatus(t *testing.T) {
	testEnv(t, false)

	status := map[string]any{"mirror": "not a mirror status"}

	var stdout bytes.Buffer

	err := run(testLogger(), []string{"cleanup"}, testInput(t, testExperiment(t, nil, status)), &stdout)
	require.ErrorContains(t, err, "executing cleanup stage: decoding app status")
	assert.Empty(t, stdout.String())
}

func TestRunKeepsTopLevelFieldsThePhenixTypesDoNotKnow(t *testing.T) {
	testEnv(t, false)

	exp := testExperiment(t, nil, nil)
	exp["x-e2e"] = map[string]any{"kept": []any{"as", "is"}, "big": json.Number("12345678901234567890")}
	exp["hosts"] = []any{map[string]any{"name": "host1"}}

	var stdout bytes.Buffer

	err := run(testLogger(), []string{"configure"}, testInput(t, exp), &stdout)
	require.NoError(t, err)

	var out map[string]json.RawMessage

	require.NoError(t, json.Unmarshal(stdout.Bytes(), &out))
	assert.JSONEq(t, `{"big": 12345678901234567890, "kept": ["as", "is"]}`, string(out["x-e2e"]))
	assert.JSONEq(t, `[{"name": "host1"}]`, string(out["hosts"]))

	// The spec still carries what configure changed.
	var spec struct {
		Topology struct {
			Nodes []struct {
				Network struct {
					Interfaces []struct {
						Name   string `json:"name"`
						Bridge string `json:"bridge"`
					} `json:"interfaces"`
				} `json:"network"`
			} `json:"nodes"`
		} `json:"topology"`
	}

	require.NoError(t, json.Unmarshal(out["spec"], &spec))
	require.Len(t, spec.Topology.Nodes, 1)

	bridges := make(map[string]string)
	for _, iface := range spec.Topology.Nodes[0].Network.Interfaces {
		bridges[iface.Name] = iface.Bridge
	}

	assert.Equal(t, map[string]string{"IF0": "", "mirror0": "phenix"}, bridges)
}

func testLogger() *slog.Logger {
	return slog.New(slog.DiscardHandler)
}

// testEnv points the app at an empty store of its own and sets whether the
// stage is a dry run.
func testEnv(t *testing.T, dryrun bool) {
	t.Helper()

	t.Setenv("PHENIX_STORE_ENDPOINT", "bolt://"+filepath.Join(t.TempDir(), "phenix.bdb"))

	if dryrun {
		t.Setenv("PHENIX_DRYRUN", "true")
	} else {
		t.Setenv("PHENIX_DRYRUN", "false")
	}
}

func testInput(t *testing.T, exp map[string]any) *bytes.Reader {
	t.Helper()

	body, err := json.Marshal(exp)
	require.NoError(t, err)

	return bytes.NewReader(body)
}

// testExperiment returns an experiment that mirrors VLAN EXP_1 to interface
// mirror0 of VM monh, which runs on cluster host host1.
func testExperiment(t *testing.T, appMetadata, appStatus map[string]any) map[string]any {
	t.Helper()

	iface := func(name, vlan, addr string) map[string]any {
		return map[string]any{
			"name": name, "type": "ethernet", "proto": "static", "vlan": vlan, "address": addr, "mask": 24,
		}
	}

	return map[string]any{
		"metadata": map[string]any{"name": "exp1"},
		"spec": map[string]any{
			"experimentName": "exp1",
			"baseDir":        t.TempDir(),
			"defaultBridge":  "phenix",
			"topology": map[string]any{
				"nodes": []any{
					map[string]any{
						"type":     "VirtualMachine",
						"general":  map[string]any{"hostname": "monh"},
						"hardware": map[string]any{"os_type": "linux"},
						"network": map[string]any{
							"interfaces": []any{
								iface("IF0", "EXP_1", "10.0.0.1"),
								iface("mirror0", "mirror", "10.248.171.254"),
							},
						},
					},
				},
			},
			"scenario": map[string]any{
				"apps": []any{
					map[string]any{
						"name":     "mirror",
						"metadata": appMetadata,
						"hosts": []any{
							map[string]any{
								"hostname": "monh",
								"metadata": map[string]any{"interface": "mirror0", "vlans": []any{"EXP_1"}},
							},
						},
					},
				},
			},
		},
		"status": map[string]any{
			"schedules": map[string]any{"monh": "host1"},
			"apps":      appStatus,
		},
	}
}
