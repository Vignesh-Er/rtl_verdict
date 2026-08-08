module spi_master (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       start,
    input  wire [7:0] tx_data,
    output reg        sclk,
    output reg        cs_n,
    output reg        mosi,
    output reg        busy
);
    reg [1:0] state;
    localparam IDLE = 2'd0, XFER = 2'd1, DONE = 2'd2;
    reg [2:0] bit_count;
    reg [7:0] shift_reg;

    always @(posedge clk) begin
        if (!rst_n) begin
            state     <= IDLE;
            sclk      <= 1'b0;
            cs_n      <= 1'b1;
            mosi      <= 1'b0;
            busy      <= 1'b0;
            bit_count <= 3'd0;
            shift_reg <= 8'd0;
        end else begin
            case (state)
                IDLE: begin
                    sclk <= 1'b0;
                    if (start) begin
                        state     <= XFER;
                        cs_n      <= 1'b0;
                        busy      <= 1'b1;
                        shift_reg <= tx_data;
                        bit_count <= 3'd0;
                    end
                end
                XFER: begin
                    sclk <= ~sclk;
                    if (sclk) begin
                        if (bit_count == 3'd0) begin
                            state <= DONE;
                        end else begin
                            bit_count <= bit_count + 3'd1;
                            shift_reg <= {shift_reg[6:0], 1'b0};
                        end
                    end
                    mosi <= shift_reg[7];
                end
                DONE: begin
                    cs_n  <= 1'b1;
                    busy  <= 1'b0;
                    state <= IDLE;
                end
                default: state <= IDLE;
            endcase
        end
    end
endmodule
