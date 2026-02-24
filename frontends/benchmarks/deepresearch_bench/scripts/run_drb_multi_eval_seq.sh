#!/bin/bash
# DRB Multi-Run Evaluation Script
# Runs the DRB evaluation multiple times sequentially and aggregates results
#
# Prerequisites:
#   - Virtual environment must be activated before running this script
#   - deploy/.env must exist with required API keys
#   - Phoenix serve should be running (optional, for tracing)
#
# Usage:
#   ./run_drb_multi_eval_seq.sh                          # Run 1 evaluation
#   ./run_drb_multi_eval_seq.sh "experiment-name"        # Run with custom output dir name
#   ./run_drb_multi_eval_seq.sh --test                   # Run single evaluation
#   ./run_drb_multi_eval_seq.sh --runs 5                 # Run 5 evaluations
#   ./run_drb_multi_eval_seq.sh --config path/to/config.yml  # Custom config

set -e  # Exit on error (but we'll handle individual run failures)

# Path configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BENCHMARK_DIR="$(dirname "$SCRIPT_DIR")"
# Go up 3 levels: deepresearch_bench -> benchmarks -> frontends -> project_root
PROJECT_ROOT="$(cd "$BENCHMARK_DIR/../../.." && pwd)"

# Default configuration
NUM_RUNS=2
CONFIG_FILE="frontends/benchmarks/deepresearch_bench/configs/config_deep_research_bench.yml"
ENV_FILE="deploy/.env"
PREFIX=""

# Create timestamp for directory naming
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --test)
            NUM_RUNS=1
            echo "Test mode: Running single evaluation"
            shift
            ;;
        --runs)
            NUM_RUNS="$2"
            shift 2
            ;;
        --config)
            CONFIG_FILE="$2"
            shift 2
            ;;
        --env)
            ENV_FILE="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS] [PREFIX]"
            echo ""
            echo "Arguments:"
            echo "  PREFIX          Optional prefix for output directory name (e.g., 'gpt5-baseline')"
            echo ""
            echo "Options:"
            echo "  --test          Run single evaluation (same as --runs 1)"
            echo "  --runs N        Number of evaluation runs (default: 2)"
            echo "  --config FILE   Config file path (default: frontends/benchmarks/deepresearch_bench/configs/config_hybrid.yml)"
            echo "  --env FILE      Environment file path (default: deploy/.env)"
            echo "  --help, -h      Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0 \"16-gpt5.2-nano-baseline\"    # Output to 16-gpt5.2-nano-baseline/"
            echo "  $0 --runs 3 \"experiment-1\"      # Run 3 times, output to experiment-1/"
            exit 0
            ;;
        *)
            if [ -z "$PREFIX" ]; then
                PREFIX="$1"
                shift
            else
                echo "Unknown option: $1"
                echo "Use --help for usage information"
                exit 1
            fi
            ;;
    esac
done

# Construct aggregated results directory (after argument parsing)
if [ -n "$PREFIX" ]; then
    AGGREGATED_DIR="${BENCHMARK_DIR}/${PREFIX}"
else
    AGGREGATED_DIR="${BENCHMARK_DIR}/aggregated_results_${TIMESTAMP}"
fi

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log() {
    echo -e "${BLUE}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1"
}

log_error() {
    echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1"
}

# Validate prerequisites
validate_prerequisites() {
    log "Validating prerequisites..."

    # Check if we're in a virtual environment
    if [ -z "$VIRTUAL_ENV" ]; then
        log_error "Virtual environment is not activated!"
        log_error "Please activate your virtual environment first:"
        log_error "  source .venv/bin/activate"
        exit 1
    fi
    log_success "Virtual environment active: $VIRTUAL_ENV"

    # Check if dotenv is available
    if ! command -v dotenv &> /dev/null; then
        log_error "dotenv command not found!"
        log_error "Please install python-dotenv: pip install python-dotenv[cli]"
        exit 1
    fi
    log_success "dotenv command available"

    # Check if nat is available
    if ! command -v nat &> /dev/null; then
        log_error "nat command not found!"
        log_error "Please ensure NAT is installed in your virtual environment"
        exit 1
    fi
    log_success "nat command available"

    # Check if env file exists
    local env_file_path="${PROJECT_ROOT}/${ENV_FILE}"
    if [ ! -f "$env_file_path" ]; then
        log_error "Environment file not found: $env_file_path"
        log_error "Please create the .env file with required API keys"
        exit 1
    fi
    log_success "Environment file exists: $env_file_path"

    # Check if config file exists
    local config_file_path="${PROJECT_ROOT}/${CONFIG_FILE}"
    if [ ! -f "$config_file_path" ]; then
        log_error "Config file not found: $config_file_path"
        exit 1
    fi
    log_success "Config file exists: $config_file_path"

    log_success "All prerequisites validated"
}

# Run a single evaluation
run_evaluation() {
    local run_num=$1
    # Use relative path from project root for nat eval
    local output_dir_relative="${AGGREGATED_DIR#$PROJECT_ROOT/}/run${run_num}"
    local log_file="${AGGREGATED_DIR}/run${run_num}/eval.log"

    log "Starting evaluation run $run_num of $NUM_RUNS..."
    log "Output directory: $output_dir_relative"

    # Create run directory for log file
    mkdir -p "${AGGREGATED_DIR}/run${run_num}"

    # Run the evaluation using dotenv
    # Use -- to separate dotenv options from nat eval command (dotenv run has its own --override flag)
    local start_time=$(date +%s)

    if dotenv -f "${PROJECT_ROOT}/${ENV_FILE}" run -- nat eval --config_file "$CONFIG_FILE" --override eval.general.output_dir "$output_dir_relative" 2>&1 | tee "$log_file"; then
        local end_time=$(date +%s)
        local duration=$((end_time - start_time))
        log_success "Run $run_num completed successfully in ${duration}s"
        return 0
    else
        local end_time=$(date +%s)
        local duration=$((end_time - start_time))
        log_error "Run $run_num failed after ${duration}s"
        return 1
    fi
}

# Main execution
main() {
    log "=========================================="
    log "DRB Multi-Run Evaluation"
    log "=========================================="
    log "Number of runs: $NUM_RUNS"
    log "Config file: $CONFIG_FILE"
    log "Environment file: $ENV_FILE"
    log "Aggregated results dir: $AGGREGATED_DIR"
    log "=========================================="

    # Change to project root
    cd "$PROJECT_ROOT"
    log "Working directory: $(pwd)"

    # Validate prerequisites
    validate_prerequisites

    # Create the aggregated results directory
    mkdir -p "$AGGREGATED_DIR"
    log "Created aggregated results directory: $AGGREGATED_DIR"

    # Log Python/nat info
    log "Python: $(which python)"
    log "nat: $(which nat)"

    # Track successful and failed runs
    local successful_runs=0
    local failed_runs=0
    local total_start_time=$(date +%s)

    # Run evaluations
    for run_num in $(seq 1 $NUM_RUNS); do
        log ""
        log "=========================================="
        log "RUN $run_num OF $NUM_RUNS"
        log "=========================================="

        # Run evaluation (continue even if it fails)
        set +e  # Don't exit on error for individual runs
        if run_evaluation $run_num; then
            ((successful_runs++))
        else
            ((failed_runs++))
        fi
        set -e
    done

    local total_end_time=$(date +%s)
    local total_duration=$((total_end_time - total_start_time))

    log ""
    log "=========================================="
    log "EVALUATION SUMMARY"
    log "=========================================="
    log "Total time: ${total_duration}s ($(($total_duration / 60))m $(($total_duration % 60))s)"
    log_success "Successful runs: $successful_runs"
    if [ $failed_runs -gt 0 ]; then
        log_error "Failed runs: $failed_runs"
    fi

    # Run aggregation if at least one run succeeded
    if [ $successful_runs -gt 0 ]; then
        log ""
        log "=========================================="
        log "RUNNING AGGREGATION"
        log "=========================================="

        python "${BENCHMARK_DIR}/scripts/aggregate_drb_scores.py" \
            --input-dir "${AGGREGATED_DIR}" \
            --output "${AGGREGATED_DIR}/aggregated_results.json"

        log_success "Aggregation complete!"
    else
        log_error "No successful runs to aggregate"
        exit 1
    fi

    log ""
    log_success "All done!"
    log "Results saved to: $AGGREGATED_DIR"
}

# Run main function
main "$@"
