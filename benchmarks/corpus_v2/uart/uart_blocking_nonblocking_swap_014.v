module uart (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       tx_start,
    input  wire [7:0] tx_data,
    output reg        tx,
    output reg        tx_busy
);
    localparam IDLE = 2'd0, START_BIT = 2'd1, DATA_BITS = 2'd2, STOP_BIT = 2'd3;
    reg [1:0] state;
    reg [2:0] bit_index;
    reg [7:0] shift_reg;

    always @(posedge clk) begin
        if (!rst_n) begin
            state     = IDLE;
            bit_index <= 3'd0;
            shift_reg <= 8'd0;
            tx        <= 1'b1;
            tx_busy   <= 1'b0;
        end else begin
            case (state)
                IDLE: begin
                    tx <= 1'b1;
                    if (tx_start) begin
                        state     <= START_BIT;
                        shift_reg <= tx_data;
                        tx_busy   <= 1'b1;
                    end
                end
                START_BIT: begin
                    tx        <= 1'b0;
                    state     <= DATA_BITS;
                    bit_index <= 3'd0;
                end
                DATA_BITS: begin
                    tx <= shift_reg[bit_index];
                    if (bit_index == 3'd7) begin
                        state <= STOP_BIT;
                    end else begin
                        bit_index <= bit_index + 3'd1;
                    end
                end
                STOP_BIT: begin
                    tx      <= 1'b1;
                    tx_busy <= 1'b0;
                    state   <= IDLE;
                end
                default: state <= IDLE;
            endcase
        end
    end
endmodule
